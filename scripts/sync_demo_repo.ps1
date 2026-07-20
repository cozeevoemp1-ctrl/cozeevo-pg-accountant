# =============================================================================
# sync_demo_repo.ps1 — one-way sync: LIVE repo → DEMO repo (separate folder+git)
#
# Usage (from live repo root):
#   powershell -File scripts\sync_demo_repo.ps1                # sync + commit
#   powershell -File scripts\sync_demo_repo.ps1 -Push          # ...and push
#   powershell -File scripts\sync_demo_repo.ps1 -DemoDir "d:\Work\Claude Projects\Kozzy-Demo"
#
# What it does:
#   1. Whitelist-copies code (src/, web/, main.py, requirements.txt, deploy demo
#      script, seed script, .env.example) into the demo repo folder.
#   2. NEVER copies: docs/, data/, memory/, tests/, one-off scripts, media,
#      node_modules, .next, .env* secrets, git history.
#   3. LEAK GATE: greps the copied tree for real credentials/phones/emails —
#      ABORTS before committing if any are found.
#   4. Commits in the demo repo with a message referencing the live commit.
#
# Demo behavior differences come from DEMO_MODE=1 at runtime — this script
# copies code mechanically and must never hand-patch files.
# =============================================================================
param(
    [string]$DemoDir = "d:\Work\Claude Projects\Kozzy-Demo",
    [switch]$Push
)

$ErrorActionPreference = "Stop"
$LiveDir = Split-Path -Parent $PSScriptRoot   # repo root (scripts/..)

# ── Whitelist ────────────────────────────────────────────────────────────────
$CopyDirs = @("src", "web")
$CopyFiles = @(
    "main.py",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "deploy\setup_demo_vps.sh",
    "scripts\seed_demo_data.py"
)
# Excluded inside copied dirs (robocopy /XD /XF)
$ExcludeDirs = @("node_modules", ".next", "test-results", "__pycache__", "e2e", "media")
$ExcludeFiles = @(".env", ".env.local", ".env.production", "*.tsbuildinfo", "*.pyc", "*.log")

# ── Sanitization transforms (applied to the DEMO copy only) ──────────────────
# Deterministic rewrites for real data living in files we cannot edit in the
# live repo (migrate_all.py is append-only; role_service keeps the real role
# map for production). Order matters: longer strings first.
$Transforms = [ordered]@{
    # phones (all formats) → reserved demo numbers
    "\+917845952289" = "+919000000001"; "917845952289" = "919000000001"; "7845952289" = "9000000001"
    "\+917358341775" = "+919000000002"; "917358341775" = "919000000002"; "7358341775" = "9000000002"
    "\+919444296681" = "+919000000003"; "919444296681" = "919000000003"; "9444296681" = "9000000003"
    "\+917680814628" = "+919000000004"; "917680814628" = "919000000004"; "7680814628" = "9000000004"
    "966534015243"   = "919000000005"
    "8106778788" = "9000000006"; "9600288048" = "9000000007"
    "9535665407" = "9000000008"; "9342205440" = "9000000009"
    # emails
    "kirankumarpemmasani@gmail\.com" = "demo-admin@example.com"
    "cozeevoemp1@gmail\.com"         = "demo-ops@example.com"
    "lakshmigorjala6@gmail\.com"     = "demo-owner@example.com"
    "devarajuluprabhakaran1@gmail\.com" = "demo-investor@example.com"
    "krish484@gmail\.com"            = "demo-user1@example.com"
    "sai1522kl@gmail\.com"           = "demo-user2@example.com"
    # distinctive surnames/full names first, then first names (word-boundary,
    # case variants listed explicitly so identifiers rename consistently)
    "Vakkalagadda" = "Sharma"; "vakkalagadda" = "sharma"
    "Jitendranath" = "Deepaknath"; "jitendranath" = "deepaknath"
    "Devarjulu" = "Rao"; "Pemmasani" = "Verma"; "Gorjala" = "Iyer"
    "Chandrasekhar" = "Rameshbabu"; "chandrasekhar" = "rameshbabu"; "CHANDRASEKHAR" = "RAMESHBABU"
    "Prabhakaran" = "Sureshkanth"; "prabhakaran" = "sureshkanth"; "PRABHAKARAN" = "SURESHKANTH"
    "\bJitendra\b" = "Deepak"; "\bjitendra\b" = "deepak"
    "\bAshokan\b" = "Mohanraj"; "\bashokan\b" = "mohanraj"
    "\bLakshmi\b" = "Meera"; "\blakshmi\b" = "meera"; "\bLAKSHMI\b" = "MEERA"
    "\bLokesh\b" = "Ravi"; "\blokesh\b" = "ravi"
    "\bKiran\b" = "Arjun"; "\bkiran\b" = "arjun"; "\bKIRAN\b" = "ARJUN"
    "\bBharathi\b" = "Kavita"; "\bbharathi\b" = "kavita"
    "\bRaghu\b" = "Vijayan"; "\braghu\b" = "vijayan"
    "\bCozeevo\b" = "DemoStay"; "\bcozeevo\b" = "demostay"; "\bCOZEEVO\b" = "DEMOSTAY"
}
$TransformExtensions = @(".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".sh", ".sql", ".example", ".json", ".html", ".css")

# ── Leak gate patterns ───────────────────────────────────────────────────────
# BLOCK = abort the sync. Real credentials, DB refs, phones, personal emails.
$BlockPatterns = @(
    "Anchorstrong",                       # DB password
    "oxiqomoilqwfxjauxhzp",               # live Supabase project ref
    "7845952289", "7358341775", "9444296681", "7680814628",   # admin phones
    "8106778788", "9600288048", "9535665407", "9342205440",   # known real numbers
    "kirankumarpemmasani", "cozeevoemp1", "lakshmigorjala6",
    "devarajuluprabhakaran1", "krish484@", "sai1522kl",
    "966534015243",
    # distinctive names — transforms must have removed every one of these
    "Prabhakaran", "prabhakaran", "Vakkalagadda", "Jitendranath",
    "Chandrasekhar", "chandrasekhar", "Pemmasani", "Gorjala", "Devarjulu"
)
# WARN = print but do not abort (common first names / brand — transformed above,
# any leftover is likely a false positive worth eyeballing)
$WarnPatterns = @("Kiran", "Lakshmi", "Lokesh", "Ashokan", "Jitendra", "Raghu", "Cozeevo", "cozeevo")

# ── 1. Prepare demo folder ───────────────────────────────────────────────────
if (-not (Test-Path $DemoDir)) { New-Item -ItemType Directory -Force $DemoDir | Out-Null }
if (-not (Test-Path (Join-Path $DemoDir ".git"))) {
    git -C $DemoDir init | Out-Null
    Write-Host "Initialized new git repo at $DemoDir"
}

# ── 2. Copy ──────────────────────────────────────────────────────────────────
foreach ($d in $CopyDirs) {
    $src = Join-Path $LiveDir $d
    $dst = Join-Path $DemoDir $d
    $xd = $ExcludeDirs | ForEach-Object { Join-Path $src $_ }
    robocopy $src $dst /MIR /XD @xd /XF @ExcludeFiles /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $d (code $LASTEXITCODE)" }
}
foreach ($f in $CopyFiles) {
    $src = Join-Path $LiveDir $f
    if (-not (Test-Path $src)) { Write-Warning "missing: $f (skipped)"; continue }
    $dst = Join-Path $DemoDir $f
    $dstParent = Split-Path -Parent $dst
    if (-not (Test-Path $dstParent)) { New-Item -ItemType Directory -Force $dstParent | Out-Null }
    Copy-Item $src $dst -Force
}

# Demo README (only if absent — not overwritten)
$readme = Join-Path $DemoDir "README.md"
if (-not (Test-Path $readme)) {
    @"
# Kozzy — Demo Instance

Sales-demo deployment of the Kozzy PG management platform. All data is fictional.
Generated from the live repo by ``sync_demo_repo.ps1`` — do not edit here; changes land in the live repo and sync over.

Deploy: see ``deploy/setup_demo_vps.sh``. Requires ``DEMO_MODE=1`` in ``.env``.
"@ | Out-File -Encoding utf8 $readme
}

# ── 2b. Stub swap: verified P&L data never ships to demo ─────────────────────
$stubSrc = Join-Path $LiveDir "src\reports\pnl_verified_data_stub.py"
$dataDst = Join-Path $DemoDir "src\reports\pnl_verified_data.py"
if (Test-Path $stubSrc) {
    Copy-Item $stubSrc $dataDst -Force
    Write-Host "Swapped pnl_verified_data.py -> demo stub."
} else {
    Write-Warning "pnl_verified_data_stub.py not found in live repo - verified P&L data may ship!"
}

# ── 2c. Sanitization transforms on the demo copy ─────────────────────────────
Write-Host "Applying sanitization transforms..."
$transformed = 0
Get-ChildItem $DemoDir -Recurse -File |
    Where-Object { $TransformExtensions -contains $_.Extension -and $_.FullName -notmatch "\\node_modules\\|\\\.git\\|\\\.next\\" } |
    ForEach-Object {
        $text = [System.IO.File]::ReadAllText($_.FullName)
        $orig = $text
        foreach ($k in $Transforms.Keys) {
            $text = [regex]::Replace($text, $k, $Transforms[$k])
        }
        if ($text -ne $orig) {
            [System.IO.File]::WriteAllText($_.FullName, $text)
            $transformed++
        }
    }
Write-Host "  $transformed files transformed."

# ── 2d. Compile check: transforms must not break Python ──────────────────────
$compileOut = & (Join-Path $LiveDir "venv\Scripts\python.exe") -m compileall -q (Join-Path $DemoDir "src") (Join-Path $DemoDir "main.py") 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "COMPILE CHECK FAILED after transforms - sync ABORTED:" -ForegroundColor Red
    $compileOut | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    exit 1
}
Write-Host "Compile check passed."

# ── 3. Leak gate ─────────────────────────────────────────────────────────────
Write-Host "Running leak gate..."
$hits = @()
foreach ($p in $BlockPatterns) {
    $found = git -C $DemoDir grep -l -I --untracked $p -- . 2>$null
    if ($found) { $hits += ($found | ForEach-Object { "$p -> $_" }) }
}
if ($hits.Count -gt 0) {
    Write-Host "`nLEAK GATE FAILED — sync ABORTED before commit:" -ForegroundColor Red
    $hits | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "Fix these in the LIVE repo (env-driven / DEMO_MODE guard), then re-sync."
    exit 1
}
foreach ($p in $WarnPatterns) {
    $found = git -C $DemoDir grep -l -I --untracked $p -- . 2>$null
    if ($found) { $found | ForEach-Object { Write-Warning "name '$p' present in $_ (comment-level, allowed)" } }
}

# ── 4. Commit (+ optional push) ──────────────────────────────────────────────
$liveHash = (git -C $LiveDir rev-parse --short HEAD).Trim()
git -C $DemoDir add -A
$status = git -C $DemoDir status --porcelain
if ($status) {
    git -C $DemoDir commit -m "sync from live @$liveHash" | Out-Null
    Write-Host "Demo repo committed (live @$liveHash)."
    if ($Push) { git -C $DemoDir push; Write-Host "Pushed." }
} else {
    Write-Host "No changes — demo already up to date with live @$liveHash."
}
