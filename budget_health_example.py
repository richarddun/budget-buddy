#!/usr/bin/env python3
"""
Budget Health Analyzer - Usage Examples and Documentation

This file demonstrates how to use the Budget Health Analyzer both as a standalone
tool and integrated with FastAPI applications.
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path

# Import our custom modules
from budget_health_analyzer import BudgetHealthAnalyzer, BudgetHealthMetrics
from ynab_sdk_client import YNABSdkClient

def example_basic_usage():
    """
    Example 1: Basic standalone usage
    """
    print("=== Example 1: Basic Usage ===")

    # Your budget ID from YNAB (you can find this in the YNAB web app URL)
    budget_id = "d2f2e23f-f445-498d-9712-e356a90a4f64"

    try:
        # Create analyzer instance
        analyzer = BudgetHealthAnalyzer(budget_id)

        # Get metrics
        metrics = analyzer.analyze()

        # Display basic information
        print(f"Budget Health Score: {metrics.health_score:.1f}/100")
        print(f"Total Budgeted: €{metrics.total_budgeted:,.2f}")
        print(f"Total Spent: €{metrics.total_spent:,.2f}")
        print(f"Total Remaining: €{metrics.total_remaining:,.2f}")
        print(f"Overspent Categories: {len(metrics.overspent_categories)}")
        print(f"Underfunded Goals: {len(metrics.underfunded_goals)}")

        # Show spending trends
        print("\nRecent Spending Trends:")
        trends = metrics.recent_spending_trend
        print(f"  Last 7 days: €{trends['last_7_days']:,.2f}")
        print(f"  Last 14 days: €{trends['last_14_days']:,.2f}")
        print(f"  Last 30 days: €{trends['last_30_days']:,.2f}")

        return metrics

    except Exception as e:
        print(f"Error: {e}")
        return None

def example_generate_html_report():
    """
    Example 2: Generate HTML report
    """
    print("\n=== Example 2: HTML Report Generation ===")

    budget_id = "d2f2e23f-f445-498d-9712-e356a90a4f64"

    try:
        analyzer = BudgetHealthAnalyzer(budget_id)

        # Generate HTML report
        html_report = analyzer.generate_html_report()

        # Save to file
        report_path = Path("budget_health_report.html")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_report)

        print(f"HTML report saved to: {report_path.absolute()}")
        print("Open the file in your browser to view the interactive report.")

        return str(report_path.absolute())

    except Exception as e:
        print(f"Error generating HTML report: {e}")
        return None

def example_analyze_specific_areas():
    """
    Example 3: Analyze specific areas of the budget
    """
    print("\n=== Example 3: Detailed Analysis ===")

    budget_id = "d2f2e23f-f445-498d-9712-e356a90a4f64"

    try:
        analyzer = BudgetHealthAnalyzer(budget_id)
        metrics = analyzer.analyze()

        # Focus on problem areas
        print("🚨 OVERSPENT CATEGORIES:")
        if metrics.overspent_categories:
            for i, category in enumerate(metrics.overspent_categories[:5], 1):
                print(f"  {i}. {category['name']}: {category['overspent_display']} over budget")
        else:
            print("  ✅ No overspent categories!")

        print("\n🎯 UNDERFUNDED GOALS:")
        if metrics.underfunded_goals:
            for i, goal in enumerate(metrics.underfunded_goals[:5], 1):
                progress = goal['percentage_complete']
                print(f"  {i}. {goal['name']}: {goal['under_funded_display']} needed ({progress:.1f}% complete)")
        else:
            print("  ✅ All goals are properly funded!")

        print("\n💰 TOP SPENDING CATEGORIES:")
        for i, category in enumerate(metrics.top_spending_categories[:5], 1):
            print(f"  {i}. {category['name']}: {category['amount_display']}")

        print("\n🏪 TOP PAYEES:")
        for i, payee in enumerate(metrics.spending_by_payee[:5], 1):
            print(f"  {i}. {payee['name']}: {payee['amount_display']}")

    except Exception as e:
        print(f"Error in detailed analysis: {e}")

def example_fastapi_integration():
    """
    Example 4: FastAPI Integration

    This shows how to integrate the budget health analyzer into your FastAPI app
    """
    print("\n=== Example 4: FastAPI Integration ===")

    # Here's how you would add budget health endpoints to your existing FastAPI app
    fastapi_example = '''
    from fastapi import FastAPI
    from budget_health_api import app as health_app
    from budget_health_analyzer import BudgetHealthAnalyzer

    # Your existing FastAPI app
    app = FastAPI(title="Your Budget App")

    # Mount the health API as a sub-application
    app.mount("/health", health_app)

    # Or add individual endpoints to your main app:

    @app.get("/budget/{budget_id}/health-summary")
    async def get_health_summary(budget_id: str):
        analyzer = BudgetHealthAnalyzer(budget_id)
        metrics = analyzer.analyze()

        return {
            "health_score": metrics.health_score,
            "status": "excellent" if metrics.health_score >= 80 else "needs_attention",
            "overspent_count": len(metrics.overspent_categories),
            "total_remaining": metrics.total_remaining
        }

    # Run with: uvicorn your_app:app --reload
    '''

    print("FastAPI Integration Code:")
    print(fastapi_example)

    print("\nAvailable endpoints after integration:")
    endpoints = [
        "GET /health/budget/{budget_id}/health/report - Full HTML report",
        "GET /health/budget/{budget_id}/health/summary - JSON summary",
        "GET /health/budget/{budget_id}/health/detailed - Detailed JSON data",
        "GET /health/budget/{budget_id}/health/score - Just the health score",
        "GET /health/budget/{budget_id}/health/alerts - Alerts and warnings",
        "POST /health/budget/{budget_id}/health/refresh - Refresh cache"
    ]

    for endpoint in endpoints:
        print(f"  {endpoint}")

def example_configuration_options():
    """
    Example 5: Configuration and Customization
    """
    print("\n=== Example 5: Configuration Options ===")

    # Environment variables needed
    env_vars = {
        "YNAB_TOKEN": "Your YNAB Personal Access Token",
        "PORT": "8000 (optional, for FastAPI server)"
    }

    print("Required Environment Variables:")
    for var, desc in env_vars.items():
        status = "✅ Set" if os.getenv(var) else "❌ Not Set"
        print(f"  {var}: {desc} [{status}]")

    # Cache configuration
    print(f"\nCache Configuration:")
    print(f"  Cache TTL: {YNABSdkClient.CACHE_TTL_HOURS} hours")
    print(f"  Cache Directory: .ynab_cache/")

    # Customization options
    print("\nCustomization Options:")
    customizations = [
        "Modify CACHE_TTL_HOURS in YNABSdkClient for different cache duration",
        "Adjust health score calculation in _calculate_health_score()",
        "Customize HTML styling in generate_html_report()",
        "Add new metrics in BudgetHealthMetrics dataclass",
        "Extend analysis periods in _analyze_spending_trends()"
    ]

    for option in customizations:
        print(f"  • {option}")

def example_error_handling():
    """
    Example 6: Error Handling Best Practices
    """
    print("\n=== Example 6: Error Handling ===")

    budget_id = "invalid-budget-id"  # This will cause an error

    try:
        analyzer = BudgetHealthAnalyzer(budget_id)
        metrics = analyzer.analyze()

    except ValueError as e:
        print(f"❌ Configuration Error: {e}")
        print("   Solution: Check your budget ID and YNAB token")

    except ConnectionError as e:
        print(f"❌ Network Error: {e}")
        print("   Solution: Check internet connection and YNAB API status")

    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        print("   Solution: Check logs for more details")

    # Best practices for error handling
    print("\n🛡️ Error Handling Best Practices:")
    practices = [
        "Always wrap analyzer calls in try/except blocks",
        "Handle specific exception types appropriately",
        "Provide meaningful error messages to users",
        "Log errors for debugging purposes",
        "Implement retry logic for network issues",
        "Validate budget_id format before making API calls",
        "Check YNAB_TOKEN is set and valid"
    ]

    for practice in practices:
        print(f"  • {practice}")

def example_performance_tips():
    """
    Example 7: Performance Optimization Tips
    """
    print("\n=== Example 7: Performance Tips ===")

    tips = [
        "💾 Use caching - analyzer automatically caches YNAB data for 6 hours",
        "🔄 Refresh cache only when needed with refresh_budget_health_cache()",
        "⚡ Use async endpoints in production to avoid blocking",
        "📊 Limit data ranges - get only what you need for analysis",
        "🏃‍♂️ Run analysis in background for heavy usage",
        "📈 Cache HTML reports at application level for frequent access",
        "🎯 Use specific endpoints (/score) for simple checks",
        "🗃️ Consider database storage for historical trend analysis"
    ]

    for tip in tips:
        print(f"  {tip}")

def run_complete_example():
    """
    Run all examples in sequence
    """
    print("🏦 Budget Health Analyzer - Complete Example Suite")
    print("=" * 60)

    # Check prerequisites
    if not os.getenv("YNAB_TOKEN"):
        print("⚠️  Warning: YNAB_TOKEN not set. Some examples may fail.")
        print("   Get your token from: https://app.youneedabudget.com/settings/developer")
        print()

    # Run examples
    examples = [
        example_basic_usage,
        example_generate_html_report,
        example_analyze_specific_areas,
        example_fastapi_integration,
        example_configuration_options,
        example_error_handling,
        example_performance_tips
    ]

    for example_func in examples:
        try:
            example_func()
            print()
        except KeyboardInterrupt:
            print("\n\n👋 Examples interrupted by user.")
            break
        except Exception as e:
            print(f"❌ Example failed: {e}")
            print()

    print("✅ Example suite completed!")
    print("\nNext steps:")
    print("1. Set your YNAB_TOKEN environment variable")
    print("2. Update budget_id with your actual YNAB budget ID")
    print("3. Run: python budget_health_analyzer.py")
    print("4. Or start the API server: python budget_health_api.py")

if __name__ == "__main__":
    run_complete_example()
