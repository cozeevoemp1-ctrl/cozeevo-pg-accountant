"""
Single-file HTML dashboard generator using Jinja2.
No external JS frameworks — pure HTML/CSS/Chart.js CDN.
Auto-deletes after 24 hours (see cleanup.py).
"""
from __future__ import annotations

from datetime import datetime
from jinja2 import Template

DASHBOARD_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>PG Accountant — {{ period_label }}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5; color: #1a1a2e; }
  header { background: #1F4E79; color: white; padding: 1.5rem 2rem; }
  header h1 { font-size: 1.6rem; }
  header p  { opacity: .75; font-size: .9rem; margin-top: .3rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; padding: 1.5rem 2rem; }
  .card { background: white; border-radius: 12px; padding: 1.2rem 1.5rem; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  .card .label { font-size: .8rem; color: #666; text-transform: uppercase; letter-spacing: .05em; }
  .card .value { font-size: 1.8rem; font-weight: 700; margin-top: .3rem; }
  .green { color: #1a7a4a; }
  .red   { color: #c0392b; }
  .blue  { color: #2e86de; }
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; padding: 0 2rem 2rem; }
  @media (max-width: 700px) { .charts { grid-template-columns: 1fr; } }
  .chart-card { background: white; border-radius: 12px; padding: 1.2rem; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  .chart-card h3 { margin-bottom: 1rem; font-size: 1rem; color: #444; }
  table { width: 100%; border-collapse: collapse; font-size: .88rem; }
  th { background: #1F4E79; color: white; padding: .5rem .8rem; text-align: left; }
  td { padding: .45rem .8rem; border-bottom: 1px solid #eee; }
  tr:nth-child(even) { background: #f7f8fc; }
  .section { padding: 0 2rem 2rem; }
  .section h2 { margin-bottom: 1rem; font-size: 1.1rem; color: #333; }
  .badge-paid { background: #d4edda; color: #155724; padding: .2rem .6rem; border-radius: 20px; font-size: .78rem; }
  .badge-pend { background: #f8d7da; color: #721c24; padding: .2rem .6rem; border-radius: 20px; font-size: .78rem; }
  footer { text-align: center; padding: 1rem; color: #999; font-size: .8rem; }
</style>
</head>
<body>

<header>
  <h1>PG Accountant — {{ period_label }}</h1>
  <p>Generated: {{ generated_at }} &nbsp;|&nbsp; Auto-deletes in 24 hours</p>
</header>

<!-- KPI Cards -->
<div class="grid">
  <div class="card">
    <div class="label">Total Income</div>
    <div class="value green">₹{{ "{:,.0f}".format(total_income) }}</div>
  </div>
  <div class="card">
    <div class="label">Total Expense</div>
    <div class="value red">₹{{ "{:,.0f}".format(total_expense) }}</div>
  </div>
  <div class="card">
    <div class="label">Net Income</div>
    <div class="value {{ 'green' if net_income >= 0 else 'red' }}">₹{{ "{:,.0f}".format(net_income) }}</div>
  </div>
  <div class="card">
    <div class="label">Transactions</div>
    <div class="value blue">{{ txn_count }}</div>
  </div>
  {% if rent %}
  <div class="card">
    <div class="label">Rent Collected</div>
    <div class="value green">₹{{ "{:,.0f}".format(rent.collected) }}</div>
  </div>
  <div class="card">
    <div class="label">Rent Pending</div>
    <div class="value {{ 'red' if rent.pending > 0 else 'green' }}">₹{{ "{:,.0f}".format(rent.pending) }}</div>
  </div>
  {% endif %}
</div>

<!-- Charts -->
<div class="charts">
  <div class="chart-card">
    <h3>Expense by Category</h3>
    <canvas id="expenseChart" height="280"></canvas>
  </div>
  <div class="chart-card">
    <h3>Income vs Expense</h3>
    <canvas id="incomeExpenseChart" height="280"></canvas>
  </div>
</div>

<!-- Category Table -->
<div class="section">
  <h2>Category Breakdown</h2>
  <table>
    <thead><tr><th>Category</th><th>Income (₹)</th><th>Expense (₹)</th><th>Net (₹)</th></tr></thead>
    <tbody>
    {% for cat, vals in categories %}
    <tr>
      <td>{{ cat }}</td>
      <td>{{ "{:,.0f}".format(vals.income) if vals.income else "—" }}</td>
      <td>{{ "{:,.0f}".format(vals.expense) if vals.expense else "—" }}</td>
      <td class="{{ 'green' if vals.income - vals.expense >= 0 else 'red' }}">
        {{ "{:,.0f}".format(vals.income - vals.expense) }}
      </td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
</div>

{% if rent and rent.details %}
<!-- Rent Table -->
<div class="section">
  <h2>Rent Collection</h2>
  <table>
    <thead><tr><th>Tenant</th><th>Room</th><th>Expected (₹)</th><th>Status</th></tr></thead>
    <tbody>
    {% for d in rent.details %}
    <tr>
      <td>{{ d.customer }}</td>
      <td>{{ d.room or "—" }}</td>
      <td>{{ "{:,.0f}".format(d.expected) }}</td>
      <td><span class="{{ 'badge-paid' if d.paid else 'badge-pend' }}">{{ "Paid" if d.paid else "Pending" }}</span></td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

{% if salary and salary.details %}
<!-- Salary Table -->
<div class="section">
  <h2>Salary Payments</h2>
  <table>
    <thead><tr><th>Employee</th><th>Role</th><th>Salary (₹)</th><th>Status</th></tr></thead>
    <tbody>
    {% for d in salary.details %}
    <tr>
      <td>{{ d.employee }}</td>
      <td>{{ d.role or "—" }}</td>
      <td>{{ "{:,.0f}".format(d.expected) }}</td>
      <td><span class="{{ 'badge-paid' if d.paid else 'badge-pend' }}">{{ "Paid" if d.paid else "Pending" }}</span></td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

<footer>PG Accountant · Auto-generated · Confidential</footer>

<script>
// Expense pie chart
const expCtx = document.getElementById('expenseChart').getContext('2d');
new Chart(expCtx, {
  type: 'doughnut',
  data: {
    labels: {{ expense_labels | tojson }},
    datasets: [{ data: {{ expense_values | tojson }},
      backgroundColor: ['#1F4E79','#2E86DE','#A8D8EA','#F6D860','#FF6B6B','#6BCB77','#845EC2','#FFC75F','#F9F871','#4D8076'] }]
  },
  options: { plugins: { legend: { position: 'bottom' } }, cutout: '55%' }
});

// Bar chart
const barCtx = document.getElementById('incomeExpenseChart').getContext('2d');
new Chart(barCtx, {
  type: 'bar',
  data: {
    labels: ['This Period'],
    datasets: [
      { label: 'Income', data: [{{ total_income }}], backgroundColor: '#1a7a4a' },
      { label: 'Expense', data: [{{ total_expense }}], backgroundColor: '#c0392b' }
    ]
  },
  options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { beginAtZero: true } } }
});
</script>
</body>
</html>
"""


def generate_html_dashboard(data: dict, period: str = "monthly") -> str:
    """Render the Jinja2 template with reconciliation data."""
    by_cat = data.get("by_category", {})
    categories = sorted(by_cat.items(), key=lambda x: x[1].get("expense", 0), reverse=True)

    # Chart data
    expense_items = [(cat, v.get("expense", 0)) for cat, v in categories if v.get("expense", 0) > 0]
    expense_labels = [c for c, _ in expense_items[:10]]
    expense_values = [round(v, 0) for _, v in expense_items[:10]]

    rent   = data.get("rent_summary")
    salary = data.get("salary_summary")

    tmpl = Template(DASHBOARD_TEMPLATE)
    return tmpl.render(
        period_label   = data.get("month_name") or f"{period.title()} Report",
        generated_at   = datetime.now().strftime("%d %b %Y %H:%M"),
        total_income   = data.get("total_income", 0),
        total_expense  = data.get("total_expense", 0),
        net_income     = data.get("net_income", 0),
        txn_count      = data.get("txn_count", 0),
        categories     = categories,
        expense_labels = expense_labels,
        expense_values = expense_values,
        rent           = rent,
        salary         = salary,
    )
