export function indianNumber(n: number): string {
  // Decimal-safe: group only the integer part (lakh grouping), keep ≤2 decimals.
  const fixed = Number.isInteger(n) ? Math.abs(n).toString() : Math.abs(n).toFixed(2);
  const [intPart, fracPart] = fixed.split(".");
  const last3 = intPart.slice(-3);
  const rest = intPart.slice(0, -3);
  const withCommas = rest.length
    ? rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3
    : last3;
  const out = fracPart ? `${withCommas}.${fracPart}` : withCommas;
  return n < 0 ? `-${out}` : out;
}

export function rupee(n: number): string {
  if (n < 0) {
    return `-₹${indianNumber(-n)}`;
  }
  return `₹${indianNumber(n)}`;
}

export function rupeeL(n: number): string {
  return rupee(n);
}

/** Rounded to whole rupees: 1234.56 → "₹1,235". Use for computed amounts. */
export function rupeeExact(n: number): string {
  return rupee(Math.round(n));
}

/** Compact: 1.2Cr / 4.5L / 12.3K / ₹950. Negative-safe. Use in dense cards/charts. */
export function rupeeShort(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(2)}Cr`;
  if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(1)}L`;
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K`;
  return `${sign}₹${Math.round(abs)}`;
}
