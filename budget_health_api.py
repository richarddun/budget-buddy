#!/usr/bin/env python3
"""
Budget Health API - FastAPI Integration

This module provides FastAPI routes for the budget health analyzer.
Includes both HTML and JSON endpoints for budget health data.
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import logging

from budget_health_analyzer import BudgetHealthAnalyzer, BudgetHealthMetrics

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Budget Buddy Health API",
    description="API for analyzing YNAB budget health",
    version="1.0.0"
)

# Thread pool for running sync operations async
executor = ThreadPoolExecutor(max_workers=2)

# Pydantic models for API responses
class BudgetOverview(BaseModel):
    total_budgeted: float
    total_spent: float
    total_remaining: float
    health_score: float

class CategoryInfo(BaseModel):
    name: str
    budgeted: float
    spent: float
    balance: float
    utilization: float

class SpendingTrend(BaseModel):
    last_7_days: float
    last_14_days: float
    last_30_days: float
    daily_average_30d: float

class BudgetHealthResponse(BaseModel):
    budget_overview: BudgetOverview
    spending_trends: SpendingTrend
    overspent_categories_count: int
    underfunded_goals_count: int
    top_spending_categories: list
    health_status: str
    generated_at: str

# Cache for analyzer instances (in production, use Redis or similar)
_analyzer_cache: Dict[str, BudgetHealthAnalyzer] = {}

def get_analyzer(budget_id: str) -> BudgetHealthAnalyzer:
    """Get or create analyzer instance for budget ID"""
    if budget_id not in _analyzer_cache:
        _analyzer_cache[budget_id] = BudgetHealthAnalyzer(budget_id)
    return _analyzer_cache[budget_id]

def determine_health_status(health_score: float) -> str:
    """Determine health status from score"""
    if health_score >= 80:
        return "Excellent"
    elif health_score >= 60:
        return "Good"
    elif health_score >= 40:
        return "Fair"
    else:
        return "Poor"

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Budget Buddy Health API",
        "version": "1.0.0",
        "endpoints": {
            "html_report": "/budget/{budget_id}/health/report",
            "json_summary": "/budget/{budget_id}/health/summary",
            "detailed_json": "/budget/{budget_id}/health/detailed",
            "health_score": "/budget/{budget_id}/health/score"
        }
    }

@app.get("/budget/{budget_id}/health/report", response_class=HTMLResponse)
async def get_budget_health_report(budget_id: str):
    """
    Get comprehensive budget health report as HTML

    Args:
        budget_id: YNAB budget ID

    Returns:
        HTML report with budget health analysis
    """
    try:
        analyzer = get_analyzer(budget_id)

        # Run the analysis in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        html_report = await loop.run_in_executor(
            executor, analyzer.generate_html_report
        )

        return HTMLResponse(content=html_report, status_code=200)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating budget health report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/budget/{budget_id}/health/summary", response_model=BudgetHealthResponse)
async def get_budget_health_summary(budget_id: str):
    """
    Get budget health summary as JSON

    Args:
        budget_id: YNAB budget ID

    Returns:
        JSON with budget health summary
    """
    try:
        analyzer = get_analyzer(budget_id)

        # Run the analysis in a thread pool
        loop = asyncio.get_event_loop()
        metrics: BudgetHealthMetrics = await loop.run_in_executor(
            executor, analyzer.analyze
        )

        # Convert to API response format
        response = BudgetHealthResponse(
            budget_overview=BudgetOverview(
                total_budgeted=metrics.total_budgeted,
                total_spent=metrics.total_spent,
                total_remaining=metrics.total_remaining,
                health_score=metrics.health_score
            ),
            spending_trends=SpendingTrend(
                last_7_days=metrics.recent_spending_trend['last_7_days'],
                last_14_days=metrics.recent_spending_trend['last_14_days'],
                last_30_days=metrics.recent_spending_trend['last_30_days'],
                daily_average_30d=metrics.recent_spending_trend['last_30_days'] / 30
            ),
            overspent_categories_count=len(metrics.overspent_categories),
            underfunded_goals_count=len(metrics.underfunded_goals),
            top_spending_categories=metrics.top_spending_categories[:5],
            health_status=determine_health_status(metrics.health_score),
            generated_at=datetime.now().isoformat()
        )

        return response

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating budget health summary: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/budget/{budget_id}/health/detailed")
async def get_budget_health_detailed(budget_id: str):
    """
    Get detailed budget health data as JSON

    Args:
        budget_id: YNAB budget ID

    Returns:
        Comprehensive JSON with all budget health data
    """
    try:
        analyzer = get_analyzer(budget_id)

        # Run the analysis in a thread pool
        loop = asyncio.get_event_loop()
        metrics: BudgetHealthMetrics = await loop.run_in_executor(
            executor, analyzer.analyze
        )

        # Return all metrics data
        return {
            "health_score": metrics.health_score,
            "health_status": determine_health_status(metrics.health_score),
            "budget_totals": {
                "total_budgeted": metrics.total_budgeted,
                "total_spent": metrics.total_spent,
                "total_remaining": metrics.total_remaining
            },
            "spending_trends": {
                **metrics.recent_spending_trend,
                "daily_average_30d": metrics.recent_spending_trend['last_30_days'] / 30
            },
            "overspent_categories": metrics.overspent_categories,
            "underfunded_goals": metrics.underfunded_goals,
            "account_summary": metrics.account_summary,
            "category_analysis": metrics.category_analysis[:10],
            "top_spending_categories": metrics.top_spending_categories,
            "spending_by_payee": metrics.spending_by_payee,
            "generated_at": datetime.now().isoformat()
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating detailed budget health data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/budget/{budget_id}/health/score")
async def get_budget_health_score(budget_id: str):
    """
    Get just the budget health score

    Args:
        budget_id: YNAB budget ID

    Returns:
        JSON with health score and status
    """
    try:
        analyzer = get_analyzer(budget_id)

        # Run the analysis in a thread pool
        loop = asyncio.get_event_loop()
        metrics: BudgetHealthMetrics = await loop.run_in_executor(
            executor, analyzer.analyze
        )

        return {
            "health_score": metrics.health_score,
            "health_status": determine_health_status(metrics.health_score),
            "generated_at": datetime.now().isoformat()
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting budget health score: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/budget/{budget_id}/health/alerts")
async def get_budget_alerts(budget_id: str):
    """
    Get budget alerts and warnings

    Args:
        budget_id: YNAB budget ID

    Returns:
        JSON with alerts and warnings
    """
    try:
        analyzer = get_analyzer(budget_id)

        # Run the analysis in a thread pool
        loop = asyncio.get_event_loop()
        metrics: BudgetHealthMetrics = await loop.run_in_executor(
            executor, analyzer.analyze
        )

        alerts = []

        # Critical alerts
        if metrics.overspent_categories:
            alerts.append({
                "type": "critical",
                "category": "overspending",
                "message": f"{len(metrics.overspent_categories)} categories are overspent",
                "details": metrics.overspent_categories[:3]  # Top 3 worst
            })

        # Warning alerts
        if metrics.underfunded_goals:
            alerts.append({
                "type": "warning",
                "category": "goals",
                "message": f"{len(metrics.underfunded_goals)} goals are underfunded",
                "details": metrics.underfunded_goals[:3]  # Top 3 underfunded
            })

        # Info alerts
        if metrics.health_score >= 80:
            alerts.append({
                "type": "success",
                "category": "health",
                "message": "Budget is in excellent health!",
                "details": {"health_score": metrics.health_score}
            })
        elif metrics.health_score < 60:
            alerts.append({
                "type": "warning",
                "category": "health",
                "message": f"Budget health needs attention (Score: {metrics.health_score:.0f})",
                "details": {"health_score": metrics.health_score}
            })

        return {
            "alerts": alerts,
            "alert_count": len(alerts),
            "generated_at": datetime.now().isoformat()
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting budget alerts: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/budget/{budget_id}/health/refresh")
async def refresh_budget_health_cache(budget_id: str):
    """
    Refresh the budget health cache for a specific budget

    Args:
        budget_id: YNAB budget ID

    Returns:
        Confirmation of cache refresh
    """
    try:
        # Remove from cache to force fresh data
        if budget_id in _analyzer_cache:
            del _analyzer_cache[budget_id]

        # Create new analyzer instance (will fetch fresh data)
        analyzer = get_analyzer(budget_id)

        # Clear the YNAB client cache
        analyzer.client.clear_cache()

        return {
            "message": "Budget health cache refreshed successfully",
            "budget_id": budget_id,
            "refreshed_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error refreshing budget health cache: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Health check endpoint
@app.get("/health")
async def health_check():
    """API health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "budget-health-api"
    }

# Example of how to run the server
if __name__ == "__main__":
    import uvicorn

    # Get port from environment or use default
    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "budget_health_api:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )
