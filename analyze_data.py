import pandas as pd
import json
import os

def analyze_data(csv_path):
    # Load the data
    df = pd.read_csv(csv_path)
    
    # Standardize column names (in case of leading/trailing spaces)
    df.columns = [c.strip() for c in df.columns]
    
    # All branches list
    branches = sorted(df['Company'].unique().tolist())
    
    # Data for the Entire Organization (Overall)
    overall_data = {
        'revenue': float(df[df['Category'] == 'Income']['Amount'].sum()),
        'cogs': float(df[df['Category'] == 'Cost of Goods Sold']['Amount'].sum()),
        'expenses': float(df[df['Category'] == 'Expenses']['Amount'].sum()),
    }
    overall_data['profit'] = overall_data['revenue'] - overall_data['cogs'] - overall_data['expenses']
    overall_data['margin'] = round((overall_data['profit'] / overall_data['revenue'] * 100), 2) if overall_data['revenue'] else 0
    overall_data['expense_breakdown'] = df[df['Category'] == 'Expenses'].groupby('Account')['Amount'].sum().to_dict()

    # Data per Branch
    company_data_map = {}
    for branch in branches:
        branch_df = df[df['Company'] == branch]
        rev = float(branch_df[branch_df['Category'] == 'Income']['Amount'].sum())
        cogs = float(branch_df[branch_df['Category'] == 'Cost of Goods Sold']['Amount'].sum())
        exp = float(branch_df[branch_df['Category'] == 'Expenses']['Amount'].sum())
        profit = rev - cogs - exp
        margin = round((profit / rev * 100), 2) if rev else 0
        
        company_data_map[branch] = {
            'revenue': rev,
            'cogs': cogs,
            'expenses': exp,
            'profit': profit,
            'margin': margin,
            'expense_breakdown': branch_df[branch_df['Category'] == 'Expenses'].groupby('Account')['Amount'].sum().to_dict()
        }

    return {
        'branches': branches,
        'overall': overall_data,
        'company_map': company_data_map
    }

def generate_html(data, output_path):
    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Financial Performance Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --primary: #2563eb;
            --success: #10b981;
            --danger: #ef4444;
            --text-main: #1e293b;
            --text-muted: #64748b;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        header {{
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .filter-section {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        select {{
            padding: 8px 16px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            font-size: 1rem;
            cursor: pointer;
            background: white;
            outline: none;
        }}
        h1 {{
            font-size: 1.75rem;
            margin: 0;
            color: var(--text-main);
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        .stat-card {{
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            border: 1px solid #e2e8f0;
        }}
        .stat-label {{
            font-size: 0.875rem;
            color: var(--text-muted);
            margin-bottom: 10px;
        }}
        .stat-value {{
            font-size: 1.5rem;
            font-weight: 700;
        }}
        .charts-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 40px;
        }}
        .chart-container, .table-container {{
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            border: 1px solid #e2e8f0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }}
        th {{
            background-color: #f1f5f9;
            font-weight: 600;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        .profit-positive {{ color: var(--success); }}
        .profit-negative {{ color: var(--danger); }}
        
        @media (max-width: 900px) {{
            .charts-grid {{ grid-template-columns: 1fr; }}
            header {{ flex-direction: column; gap: 20px; text-align: center; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>Financial Dashboard</h1>
                <p style="color: var(--text-muted); margin: 5px 0 0 0;">Performance Overview & Analysis</p>
            </div>
            <div class="filter-section">
                <label for="companyFilter">Filter by Branch:</label>
                <select id="companyFilter" onchange="updateDashboard()">
                    <option value="Overall">Overall Organization</option>
                    {"".join([f'<option value="{b}">{b}</option>' for b in data['branches']])}
                </select>
            </div>
        </header>

        <div class="summary-grid">
            <div class="stat-card">
                <div class="stat-label">Revenue</div>
                <div class="stat-value" id="cardRevenue">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">COGS</div>
                <div class="stat-value" id="cardCOGS">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Expenses</div>
                <div class="stat-value" id="cardExpenses">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Net Profit</div>
                <div class="stat-value" id="cardProfit">$0.00</div>
            </div>
        </div>

        <div class="charts-grid">
            <div class="chart-container">
                <h3 id="chartTitle">Expense Distribution</h3>
                <div style="height: 300px; display: flex; justify-content: center;">
                    <canvas id="expenseChart"></canvas>
                </div>
            </div>
            <div class="table-container">
                <h3>Expense Breakdown (Tabular)</h3>
                <div style="max-height: 300px; overflow-y: auto;">
                    <table id="expenseTable">
                        <thead>
                            <tr>
                                <th>Account</th>
                                <th>Amount</th>
                            </tr>
                        </thead>
                        <tbody id="expenseTableBody">
                            <!-- Populated by JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="table-container" id="branchComparisonContainer">
            <h3>Branch Comparison</h3>
            <table>
                <thead>
                    <tr>
                        <th>Branch</th>
                        <th>Revenue</th>
                        <th>Net Profit</th>
                        <th>Margin (%)</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join([f"<tr><td>{b}</td><td>${data['company_map'][b]['revenue']:,}</td><td class='{'profit-positive' if data['company_map'][b]['profit'] >= 0 else 'profit-negative'}'>${data['company_map'][b]['profit']:,}</td><td>{data['company_map'][b]['margin']}%</td></tr>" for b in data['branches']])}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        const dashboardData = {json.dumps(data)};
        let expenseChart = null;

        function formatCurrency(value) {{
            return new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD' }}).format(value);
        }}

        function updateDashboard() {{
            const selected = document.getElementById('companyFilter').value;
            const source = selected === 'Overall' ? dashboardData.overall : dashboardData.company_map[selected];
            
            // Update Cards
            document.getElementById('cardRevenue').innerText = formatCurrency(source.revenue);
            document.getElementById('cardCOGS').innerText = formatCurrency(source.cogs);
            document.getElementById('cardExpenses').innerText = formatCurrency(source.expenses);
            
            const profitEl = document.getElementById('cardProfit');
            profitEl.innerText = formatCurrency(source.profit);
            profitEl.className = 'stat-value ' + (source.profit >= 0 ? 'profit-positive' : 'profit-negative');

            // Update Chart
            updateChart(source.expense_breakdown);

            // Update Table
            updateExpenseTable(source.expense_breakdown);
            
            // Show/Hide Comparison
            document.getElementById('branchComparisonContainer').style.display = selected === 'Overall' ? 'block' : 'none';
        }}

        function updateChart(expenses) {{
            const labels = Object.keys(expenses);
            const values = Object.values(expenses);
            
            if (expenseChart) {{
                expenseChart.destroy();
            }}

            const ctx = document.getElementById('expenseChart').getContext('2d');
            expenseChart = new Chart(ctx, {{
                type: 'doughnut',
                data: {{
                    labels: labels,
                    datasets: [{{
                        data: values,
                        backgroundColor: [
                            '#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899', '#64748b',
                            '#06b6d4', '#84cc16', '#f43f5e', '#a855f7', '#0ea5e9', '#14b8a6', '#f97316'
                        ]
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ position: 'right', labels: {{ boxWidth: 12, font: {{ size: 10 }} }} }}
                    }}
                }}
            }});
        }}

        function updateExpenseTable(expenses) {{
            const tbody = document.getElementById('expenseTableBody');
            tbody.innerHTML = '';
            
            // Sort by amount descending
            const sortedItems = Object.entries(expenses).sort((a, b) => b[1] - a[1]);
            
            sortedItems.forEach(([account, amount]) => {{
                const row = `<tr><td>${{account}}</td><td>${{formatCurrency(amount)}}</td></tr>`;
                tbody.innerHTML += row;
            }});

            if (sortedItems.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="2" style="text-align: center;">No expenses recorded</td></tr>';
            }}
        }}

        // Initialize
        updateDashboard();
    </script>
</body>
</html>
    """
    with open(output_path, 'w') as f:
        f.write(html_template)

if __name__ == "__main__":
    data_file = "/Users/tenzinpaljor/Desktop/Personal /Data Analyse with Yang/data/data-KS-client 1 - Sheet1.csv"
    results = analyze_data(data_file)
    generate_html(results, "/Users/tenzinpaljor/Desktop/Personal /Data Analyse with Yang/index.html")
    print("Updated Dashboard generated: index.html")
