import pandas as pd
import json
import os

def analyze_data(csv_path=None, df=None):
    """
    Analyze financial data from either a CSV file path or a DataFrame.
    
    Args:
        csv_path: Path to CSV file (optional if df is provided)
        df: Pandas DataFrame (optional if csv_path is provided)
    
    Returns:
        dict: Processed dashboard data with branches, periods, overall, and company_map
    """
    if df is None:
        if csv_path is None:
            raise ValueError("Either csv_path or df must be provided")
        df = pd.read_csv(csv_path)
    
    # Standardize column names (in case of leading/trailing spaces)
    df.columns = [c.strip() for c in df.columns]
    
    # Normalize Category values to expected format
    category_map = {
        'cogs': 'Cost of Goods Sold',
        'cost of goods sold': 'Cost of Goods Sold',
        'expense': 'Expenses',
        'expenses': 'Expenses',
        'income': 'Income',
        'revenue': 'Income'
    }
    df['Category'] = df['Category'].apply(
        lambda x: category_map.get(str(x).strip().lower(), x) if pd.notna(x) else x
    )
    
    # Normalize Month values (handle full month names)
    month_name_map = {
        'january': 'Jan', 'february': 'Feb', 'march': 'Mar', 'april': 'Apr',
        'may': 'May', 'june': 'Jun', 'july': 'Jul', 'august': 'Aug',
        'september': 'Sep', 'october': 'Oct', 'november': 'Nov', 'december': 'Dec',
        'jan': 'Jan', 'feb': 'Feb', 'mar': 'Mar', 'apr': 'Apr',
        'jun': 'Jun', 'jul': 'Jul', 'aug': 'Aug', 'sep': 'Sep', 'sept': 'Sep',
        'oct': 'Oct', 'nov': 'Nov', 'dec': 'Dec', 'ytd': 'YTD', 'total': 'YTD'
    }
    df['Month'] = df['Month'].apply(
        lambda x: month_name_map.get(str(x).strip().lower(), x) if pd.notna(x) else x
    )
    
    # Filter out summary/total rows that would cause double-counting
    summary_patterns = [
        'total income', 'total expenses', 'total cost of goods sold', 
        'total cogs', 'total other income', 'total other expenses',
        'net income', 'net other income', 'net operating income', 
        'gross profit', 'net profit'
    ]
    
    def is_summary_row(account):
        if pd.isna(account):
            return False
        account_lower = str(account).strip().lower()
        # Check if it's an exact match to summary patterns
        if account_lower in summary_patterns:
            return True
        # Check if it starts with "Total " or "Total for"
        if account_lower.startswith('total ') or account_lower.startswith('total for '):
            return True
        return False
    
    df = df[~df['Account'].apply(is_summary_row)].copy()
    
    # All branches list
    branches = sorted(df['Company'].unique().tolist())
    
    # Month order for sorting (including YTD for year-to-date reports)
    month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'YTD']
    
    # Helper to calculate metrics for a dataframe
    def get_metrics(target_df):
        rev = float(target_df[target_df['Category'] == 'Income']['Amount'].sum())
        cogs = float(target_df[target_df['Category'] == 'Cost of Goods Sold']['Amount'].sum())
        exp = float(target_df[target_df['Category'] == 'Expenses']['Amount'].sum())
        profit = rev - cogs - exp
        margin = round((profit / rev * 100), 2) if rev else 0
        expense_breakdown = target_df[target_df['Category'] == 'Expenses'].groupby('Account')['Amount'].sum().to_dict()
        return {
            'revenue': rev,
            'cogs': cogs,
            'expenses': exp,
            'profit': profit,
            'margin': margin,
            'expense_breakdown': expense_breakdown
        }

    # All unique periods in chronological order
    periods = []
    for year in sorted(df['Year'].unique()):
        for month in month_order:
            if not df[(df['Month'] == month) & (df['Year'] == year)].empty:
                periods.append(f"{month} {year}")

    # Data for the Entire Organization (Overall)
    overall_metrics = get_metrics(df)
    overall_monthly = []
    for period in periods:
        month_str, year_str = period.split()
        m_df = df[(df['Month'] == month_str) & (df['Year'] == int(year_str))]
        metrics = get_metrics(m_df)
        overall_monthly.append({
            'label': period,
            **metrics
        })

    # Data per Branch
    company_data_map = {}
    for branch in branches:
        branch_df = df[df['Company'] == branch]
        branch_metrics = get_metrics(branch_df)
        
        branch_monthly = []
        for period in periods:
            month_str, year_str = period.split()
            m_df = branch_df[(branch_df['Month'] == month_str) & (branch_df['Year'] == int(year_str))]
            if not m_df.empty:
                m_metrics = get_metrics(m_df)
                branch_monthly.append({
                    'label': period,
                    **m_metrics
                })
            else:
                # Fill gaps with zero if a branch has no data for a month
                branch_monthly.append({
                    'label': period,
                    'revenue': 0, 'cogs': 0, 'expenses': 0, 'profit': 0, 'margin': 0, 'expense_breakdown': {}
                })
        
        branch_metrics['monthly_details'] = branch_monthly
        company_data_map[branch] = branch_metrics

    return {
        'branches': branches,
        'periods': periods,
        'overall': {**overall_metrics, 'monthly_details': overall_monthly},
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
            .filter-section {{ flex-direction: column; width: 100%; }}
            select {{ width: 100%; }}
        }}
        /* Chatbot Styles */
        #chat-toggle {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: var(--primary);
            color: white;
            border: none;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            z-index: 1000;
            transition: transform 0.2s;
        }}
        #chat-toggle:hover {{ transform: scale(1.05); }}
        
        #chat-container {{
            position: fixed;
            bottom: 90px;
            right: 20px;
            width: 350px;
            height: 500px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.15);
            display: none;
            flex-direction: column;
            z-index: 1000;
            overflow: hidden;
            border: 1px solid #e2e8f0;
        }}
        .chat-header {{
            background: var(--primary);
            color: white;
            padding: 15px;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        #chat-messages {{
            flex: 1;
            padding: 15px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .message {{
            max-width: 80%;
            padding: 8px 12px;
            border-radius: 12px;
            font-size: 0.9rem;
            line-height: 1.4;
        }}
        .message.user {{
            align-self: flex-end;
            background: var(--primary);
            color: white;
        }}
        .message.bot {{
            align-self: flex-start;
            background: #f1f5f9;
            color: var(--text-main);
        }}
        .chat-input-area {{
            padding: 15px;
            border-top: 1px solid #e2e8f0;
            display: flex;
            gap: 10px;
        }}
        #chat-input {{
            flex: 1;
            padding: 8px 12px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            outline: none;
        }}
        #chat-send {{
            background: var(--primary);
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 6px;
            cursor: pointer;
        }}

        /* FAQ Styles */
        .faq-section {{
            margin-top: 40px;
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            border: 1px solid #e2e8f0;
            margin-bottom: 40px;
        }}
        .faq-item {{
            border-bottom: 1px solid #e2e8f0;
            padding: 15px 0;
        }}
        .faq-item:last-child {{
            border-bottom: none;
        }}
        .faq-question {{
            font-weight: 600;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: var(--text-main);
        }}
        .faq-answer {{
            margin-top: 10px;
            color: var(--text-muted);
            font-size: 0.95rem;
            line-height: 1.5;
            display: none;
        }}
        .faq-item.active .faq-answer {{
            display: block;
        }}
        .faq-icon::after {{
            content: '+';
            font-size: 1.2rem;
            font-weight: bold;
        }}
        .faq-item.active .faq-icon::after {{
            content: '−';
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
                <div style="display: flex; flex-direction: column; gap: 5px;">
                    <label style="font-size: 0.75rem; color: var(--text-muted);">Branch</label>
                    <select id="companyFilter" onchange="updateDashboard()">
                        <option value="Overall">Overall Organization</option>
                        {"".join([f'<option value="{b}">{b}</option>' for b in data['branches']])}
                    </select>
                </div>
                <div style="display: flex; flex-direction: column; gap: 5px;">
                    <label style="font-size: 0.75rem; color: var(--text-muted);">Start Period</label>
                    <select id="startPeriod" onchange="updateDashboard()">
                        {"".join([f'<option value="{p}">{p}</option>' for p in data['periods']])}
                    </select>
                </div>
                <div style="display: flex; flex-direction: column; gap: 5px;">
                    <label style="font-size: 0.75rem; color: var(--text-muted);">End Period</label>
                    <select id="endPeriod" onchange="updateDashboard()">
                        {"".join([f'<option value="{p}" {"selected" if i == len(data["periods"])-1 else ""}>{p}</option>' for i, p in enumerate(data['periods'])])}
                    </select>
                </div>
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

        <div class="charts-grid" style="margin-top: 20px;">
            <div class="chart-container">
                <h3>Monthly Profit Trend</h3>
                <div style="height: 300px;">
                    <canvas id="monthlyChart"></canvas>
                </div>
            </div>
            <div class="stat-card" style="display: flex; flex-direction: column; justify-content: center; gap: 20px;">
                <div>
                    <div class="stat-label">Best Performing Month</div>
                    <div class="stat-value profit-positive" id="bestMonthText">-</div>
                </div>
                <div>
                    <div class="stat-label">Least Profitable Month</div>
                    <div class="stat-value profit-negative" id="worstMonthText">-</div>
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
                <tbody id="branchComparisonBody">
                    <!-- Populated by JS -->
                </tbody>
            </table>
        </div>

        <div class="faq-section">
            <h3>Business & Financial FAQ</h3>
            
            <div class="faq-item">
                <div class="faq-question" onclick="this.parentElement.classList.toggle('active')">
                    What are the industrial standards for Profit Margins in restoration?
                    <span class="faq-icon"></span>
                </div>
                <div class="faq-answer">
                    In the restoration industry, a healthy Net Profit Margin typically ranges between 15% to 25%. Mitigation services (water/mold) often command higher margins (up to 40%+) due to specialized equipment and labor, while reconstruction services typically have lower margins (10% - 15%) due to subcontracting costs.
                </div>
            </div>

            <div class="faq-item">
                <div class="faq-question" onclick="this.parentElement.classList.toggle('active')">
                    What does 'COGS' include in this report?
                    <span class="faq-icon"></span>
                </div>
                <div class="faq-answer">
                    Cost of Goods Sold (COGS) includes direct costs directly tied to revenue generation. In restoration, this primarily consists of field labor (technician wages), materials (antimicrobials, drywall, flooring), and equipment rentals or direct fuel costs for service vehicles.
                </div>
            </div>

            <div class="faq-item">
                <div class="faq-question" onclick="this.parentElement.classList.toggle('active')">
                    What is the difference between Expenses and COGS?
                    <span class="faq-icon"></span>
                </div>
                <div class="faq-answer">
                    COGS are "Direct Costs" that vary with the volume of work. Expenses (or Operating Expenses/OpEx) are "Indirect Costs" or overhead needed to keep the business running regardless of volume, such as office rent, insurance, marketing, and administrative salaries.
                </div>
            </div>

            <div class="faq-item">
                <div class="faq-question" onclick="this.parentElement.classList.toggle('active')">
                    What does a negative Net Profit mean for a specific month?
                    <span class="faq-icon"></span>
                </div>
                <div class="faq-answer">
                    A negative Net Profit (a loss) means your total costs (COGS + Expenses) exceeded your Revenue for that period. This can happen during slow seasons, months with high equipment investment, or if job costs were not properly managed.
                </div>
            </div>

            <div class="faq-item">
                <div class="faq-question" onclick="this.parentElement.classList.toggle('active')">
                    How is the 'Net Margin %' calculated?
                    <span class="faq-icon"></span>
                </div>
                <div class="faq-answer">
                    It is calculated as: (Net Profit / Total Revenue) * 100. It represents how many cents of every dollar earned actually becomes profit after all expenses are paid.
                </div>
            </div>
        </div>
    </div>

    <!-- Chatbot UI -->
    <button id="chat-toggle" onclick="toggleChat()">💬</button>
    <div id="chat-container">
        <div class="chat-header">
            <span>AI Data Assistant</span>
            <button onclick="toggleChat()" style="background:none; border:none; color:white; cursor:pointer;">✕</button>
        </div>
        <div id="chat-messages">
            <div class="message bot">Hello! I'm your AI assistant. Ask me anything about the financial data.</div>
        </div>
        <div class="chat-input-area">
            <input type="text" id="chat-input" placeholder="Type a message..." onkeypress="if(event.key === 'Enter') sendMessage()">
            <button id="chat-send" onclick="sendMessage()">Send</button>
        </div>
    </div>

    <script>
        const dashboardData = {json.dumps(data)};
        let expenseChart = null;
        let monthlyChart = null;

        function formatCurrency(value) {{
            return new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD' }}).format(value);
        }}

        function updateDashboard() {{
            const selectedBranch = document.getElementById('companyFilter').value;
            const startPeriod = document.getElementById('startPeriod').value;
            const endPeriod = document.getElementById('endPeriod').value;

            // Get relevant monthly details
            const monthlyData = selectedBranch === 'Overall' ? dashboardData.overall.monthly_details : dashboardData.company_map[selectedBranch].monthly_details;
            
            // Find indices for slicing
            const startIndex = dashboardData.periods.indexOf(startPeriod);
            const endIndex = dashboardData.periods.indexOf(endPeriod);
            
            // Ensure logical range
            if (startIndex > endIndex) {{
                alert("Start period cannot be after end period");
                return;
            }}

            // Filter data by range
            const filteredMonths = monthlyData.slice(startIndex, endIndex + 1);

            // Aggregate metrics
            let totalRevenue = 0, totalCOGS = 0, totalExpenses = 0, totalProfit = 0;
            let combinedExpenses = {{}};

            filteredMonths.forEach(m => {{
                totalRevenue += m.revenue;
                totalCOGS += m.cogs;
                totalExpenses += m.expenses;
                totalProfit += m.profit;
                
                // Merge expense breakdowns
                for (const [account, amount] of Object.entries(m.expense_breakdown)) {{
                    combinedExpenses[account] = (combinedExpenses[account] || 0) + amount;
                }}
            }});

            // Update Cards
            document.getElementById('cardRevenue').innerText = formatCurrency(totalRevenue);
            document.getElementById('cardCOGS').innerText = formatCurrency(totalCOGS);
            document.getElementById('cardExpenses').innerText = formatCurrency(totalExpenses);
            
            const profitEl = document.getElementById('cardProfit');
            profitEl.innerText = formatCurrency(totalProfit);
            profitEl.className = 'stat-value ' + (totalProfit >= 0 ? 'profit-positive' : 'profit-negative');

            // Update Best/Worst Month (within selected range)
            if (filteredMonths.length > 0) {{
                const best = filteredMonths.reduce((prev, curr) => (prev.profit > curr.profit) ? prev : curr);
                const worst = filteredMonths.reduce((prev, curr) => (prev.profit < curr.profit) ? prev : curr);
                document.getElementById('bestMonthText').innerText = `${{best.label}} (${{formatCurrency(best.profit)}})`;
                document.getElementById('worstMonthText').innerText = `${{worst.label}} (${{formatCurrency(worst.profit)}})`;
            }}

            // Update Charts
            updateChart(combinedExpenses);
            updateMonthlyChart(filteredMonths);

            // Update Table
            updateExpenseTable(combinedExpenses);
            
            // Update Branch Comparison (Only for overall view)
            if (selectedBranch === 'Overall') {{
                updateBranchComparison(startIndex, endIndex);
                document.getElementById('branchComparisonContainer').style.display = 'block';
            }} else {{
                document.getElementById('branchComparisonContainer').style.display = 'none';
            }}
        }}

        function updateBranchComparison(startIndex, endIndex) {{
            const tbody = document.getElementById('branchComparisonBody');
            tbody.innerHTML = '';

            dashboardData.branches.forEach(branch => {{
                const branchData = dashboardData.company_map[branch].monthly_details.slice(startIndex, endIndex + 1);
                
                let bRev = 0, bProfit = 0;
                branchData.forEach(m => {{
                    bRev += m.revenue;
                    bProfit += m.profit;
                }});

                const bMargin = bRev ? ((bProfit / bRev) * 100).toFixed(2) : 0;
                const profitClass = bProfit >= 0 ? 'profit-positive' : 'profit-negative';

                const row = `<tr>
                    <td>${{branch}}</td>
                    <td>${{formatCurrency(bRev)}}</td>
                    <td class="${{profitClass}}">${{formatCurrency(bProfit)}}</td>
                    <td>${{bMargin}}%</td>
                </tr>`;
                tbody.innerHTML += row;
            }});
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
                        legend: {{ position: 'right', labels: {{ boxWidth: 12, font: {{ size: 10 }} }} }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    return `${{label}}: ${{formatCurrency(value)}} (${{percentage}}%)`;
                                }}
                            }}
                        }}
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

        // Chatbot Logic
        function toggleChat() {{
            const container = document.getElementById('chat-container');
            container.style.display = container.style.display === 'flex' ? 'none' : 'flex';
        }}

        async function sendMessage() {{
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;

            addMessage(message, 'user');
            input.value = '';

            try {{
                const response = await fetch('http://localhost:8000/chat', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        message: message,
                        context: dashboardData
                    }})
                }});
                const data = await response.json();
                addMessage(data.reply || data.detail || 'Error communicating with AI Assistant', 'bot');
            }} catch (error) {{
                addMessage('Error: ' + error.message, 'bot');
            }}
        }}

        function updateMonthlyChart(trends) {{
            const labels = trends.map(t => t.label);
            const profits = trends.map(t => t.profit);
            
            if (monthlyChart) {{
                monthlyChart.destroy();
            }}

            const ctx = document.getElementById('monthlyChart').getContext('2d');
            monthlyChart = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Net Profit',
                        data: profits,
                        backgroundColor: profits.map(v => v >= 0 ? 'rgba(16, 185, 129, 0.6)' : 'rgba(239, 68, 68, 0.6)'),
                        borderColor: profits.map(v => v >= 0 ? '#10b981' : '#ef4444'),
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }}
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            ticks: {{ callback: value => formatCurrency(value) }}
                        }}
                    }}
                }}
            }});
        }}

        function addMessage(text, sender) {{
            const messages = document.getElementById('chat-messages');
            const div = document.createElement('div');
            div.className = `message ${{sender}}`;
            div.innerText = text;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
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
    # Use paths relative to this script's location
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_file = os.path.join(base_dir, "frontend", "data", "data.csv")
    output_html = os.path.join(base_dir, "frontend", "index.html")
    
    results = analyze_data(data_file)
    generate_html(results, output_html)
    print(f"Updated Dashboard generated: {output_html}")
