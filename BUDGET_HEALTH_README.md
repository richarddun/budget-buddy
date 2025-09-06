# Budget Health Analyzer

A comprehensive Python tool for analyzing YNAB (You Need A Budget) data and generating detailed budget health reports. This tool provides both standalone functionality and FastAPI integration for web applications.

## Features

- 📊 **Comprehensive Budget Analysis**: Get detailed insights into your budget performance
- 🎯 **Health Score Calculation**: 0-100 score based on spending patterns and budget adherence
- 📈 **Spending Trend Analysis**: Track spending over 7, 14, and 30-day periods
- ⚠️ **Alert System**: Identify overspent categories and underfunded goals
- 🌐 **HTML Reports**: Beautiful, interactive HTML reports with charts and visualizations
- 🚀 **FastAPI Integration**: Ready-to-use API endpoints for web applications
- 💾 **Smart Caching**: Automatic caching of YNAB data to minimize API calls
- 📱 **Mobile-Friendly**: Responsive HTML reports that work on all devices

## Quick Start

### Prerequisites

1. **YNAB Personal Access Token**: Get yours from [YNAB Developer Settings](https://app.youneedabudget.com/settings/developer)
2. **Python 3.7+**: Make sure you have Python installed
3. **YNAB Budget ID**: Found in your YNAB web app URL

### Installation

1. **Set up environment variables**:
   ```bash
   export YNAB_TOKEN="your_ynab_personal_access_token"
   ```

2. **Install dependencies** (if not already installed):
   ```bash
   pip install ynab-sdk-python python-dotenv fastapi uvicorn pydantic
   ```

3. **Find your Budget ID**:
   - Go to YNAB web app
   - Your budget ID is in the URL: `https://app.youneedabudget.com/[BUDGET_ID]/budget`

### Basic Usage

```python
from budget_health_analyzer import BudgetHealthAnalyzer

# Initialize analyzer with your budget ID
budget_id = "your-budget-id-here"
analyzer = BudgetHealthAnalyzer(budget_id)

# Generate HTML report
html_report = analyzer.generate_html_report()

# Save report to file
with open('my_budget_report.html', 'w', encoding='utf-8') as f:
    f.write(html_report)

print("Report generated! Open my_budget_report.html in your browser.")
```

### Command Line Usage

```bash
# Generate a standalone report
python budget_health_analyzer.py

# Start the FastAPI server
python budget_health_api.py
```

## API Endpoints

When using the FastAPI integration, you get these endpoints:

### HTML Reports
- `GET /budget/{budget_id}/health/report` - Full HTML health report

### JSON Data
- `GET /budget/{budget_id}/health/summary` - Quick summary
- `GET /budget/{budget_id}/health/detailed` - Comprehensive data
- `GET /budget/{budget_id}/health/score` - Just the health score
- `GET /budget/{budget_id}/health/alerts` - Warnings and alerts

### Cache Management
- `POST /budget/{budget_id}/health/refresh` - Refresh cached data

### Health Check
- `GET /health` - API health status

## Health Score Breakdown

The health score (0-100) is calculated based on:

| Factor | Impact | Description |
|--------|---------|-------------|
| **Budget Adherence** | High | Staying within budgeted amounts |
| **Overspent Categories** | High | Number of categories over budget |
| **Goal Funding** | Medium | Progress toward savings goals |
| **Spending Trends** | Medium | Recent spending patterns |

### Score Ranges:
- **80-100**: 🟢 Excellent - Budget is very healthy
- **60-79**: 🟡 Good - Minor areas for improvement
- **40-59**: 🟠 Fair - Several areas need attention
- **0-39**: 🔴 Poor - Significant budget issues

## Configuration

### Environment Variables

```bash
# Required
YNAB_TOKEN=your_personal_access_token

# Optional
PORT=8000  # For FastAPI server
```

### Cache Settings

The analyzer automatically caches YNAB data for 6 hours to minimize API calls:

```python
# Modify cache duration (in hours)
YNABSdkClient.CACHE_TTL_HOURS = 6

# Clear cache manually
analyzer.client.clear_cache()
```

## FastAPI Integration

### Option 1: Mount as Sub-Application

```python
from fastapi import FastAPI
from budget_health_api import app as health_app

app = FastAPI()
app.mount("/health", health_app)

# Endpoints available at /health/budget/{budget_id}/...
```

### Option 2: Individual Endpoints

```python
from budget_health_analyzer import BudgetHealthAnalyzer

@app.get("/my-budget-health/{budget_id}")
async def get_budget_health(budget_id: str):
    analyzer = BudgetHealthAnalyzer(budget_id)
    metrics = analyzer.analyze()
    
    return {
        "health_score": metrics.health_score,
        "overspent_categories": len(metrics.overspent_categories),
        "total_remaining": metrics.total_remaining
    }
```

## Report Contents

### HTML Report Includes:
- 📊 **Budget Overview**: Total budgeted, spent, remaining
- 📈 **Spending Trends**: 7, 14, 30-day spending analysis
- 💰 **Account Balances**: All account summaries
- ⚠️ **Overspent Categories**: Categories over budget
- 🎯 **Underfunded Goals**: Goals needing attention
- 🏷️ **Top Spending Categories**: Where your money goes
- 🏪 **Top Payees**: Biggest expenses by vendor

### JSON Data Includes:
- All HTML report data
- Raw transaction data
- Category analysis
- Spending by payee
- Goal progress details
- Account transaction counts

## Examples

### Generate Report for Specific Month

```python
from datetime import datetime, timedelta

# Analyze last 30 days only
analyzer = BudgetHealthAnalyzer(budget_id)
# The analyzer automatically looks at last 90 days of transactions
# To customize, you'd modify the _load_data method
```

### Get Quick Health Check

```python
analyzer = BudgetHealthAnalyzer(budget_id)
metrics = analyzer.analyze()

if metrics.health_score >= 80:
    print("✅ Budget is healthy!")
elif metrics.overspent_categories:
    print(f"⚠️ {len(metrics.overspent_categories)} categories overspent")
else:
    print("📊 Budget needs attention")
```

### Async Usage with FastAPI

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=2)

@app.get("/async-health/{budget_id}")
async def async_health_check(budget_id: str):
    analyzer = BudgetHealthAnalyzer(budget_id)
    
    # Run analysis in thread pool
    loop = asyncio.get_event_loop()
    metrics = await loop.run_in_executor(executor, analyzer.analyze)
    
    return {"health_score": metrics.health_score}
```

## Troubleshooting

### Common Issues

**❌ "YNAB_TOKEN not found"**
```bash
# Solution: Set your environment variable
export YNAB_TOKEN="your_token_here"
# Or create a .env file with YNAB_TOKEN=your_token_here
```

**❌ "Budget ID not found"**
- Check your budget ID in YNAB web app URL
- Ensure you have access to the budget
- Try with a different budget ID

**❌ "ConnectionError" or "TimeoutError"**
- Check internet connection
- Verify YNAB API status
- Try clearing cache: `analyzer.client.clear_cache()`

**❌ "No transactions found"**
- Check if budget has recent transactions
- Verify date ranges in analysis
- Ensure transactions aren't deleted in YNAB

### Performance Issues

**Slow report generation:**
- Use cached data (default 6 hours)
- Reduce transaction date range
- Run analysis in background for web apps

**High memory usage:**
- Clear cache periodically
- Limit number of transactions analyzed
- Use pagination for large datasets

### Debug Mode

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now you'll see detailed logs of API calls and caching
analyzer = BudgetHealthAnalyzer(budget_id)
```

## Customization

### Modify Health Score Calculation

Edit the `_calculate_health_score` method in `BudgetHealthAnalyzer`:

```python
def _calculate_health_score(self, budgeted, spent, overspent_categories, underfunded_goals):
    score = 100
    
    # Your custom scoring logic here
    # Example: Penalize overspending more heavily
    score -= len(overspent_categories) * 10  # Increased from 5
    
    return max(0, score)
```

### Add Custom Metrics

Extend the `BudgetHealthMetrics` dataclass:

```python
@dataclass
class BudgetHealthMetrics:
    # Existing fields...
    custom_metric: float = 0.0
    monthly_savings_rate: float = 0.0
```

### Customize HTML Styling

Modify the CSS in `generate_html_report()` method:

```python
# Change color scheme
health_color = "#custom_color"

# Modify CSS styles in the HTML template
style = """
    body { 
        font-family: 'Your Font', sans-serif; 
        background: linear-gradient(45deg, #yourcolor1, #yourcolor2);
    }
"""
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is part of the Budget Buddy system and follows the same licensing terms.

## Support

- Check the troubleshooting section above
- Review the examples in `budget_health_example.py`
- Open an issue for bugs or feature requests
- Check YNAB API documentation for API-related issues

## Changelog

### v1.0.0
- Initial release
- HTML report generation
- FastAPI integration
- Caching system
- Health score calculation
- Spending trend analysis
- Alert system