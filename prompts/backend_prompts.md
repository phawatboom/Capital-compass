# Backend Development Prompts

## Running the Backend
```
How do I run my Django backend for the beta forecasting model? I'm getting [specific error message]. What are the command line arguments and typical workflows?
```

## Database Setup and Migration
```
I need help setting up the database for the beta coefficient models. How do I run migrations for the new BetaRealized and ForecastEvaluation models?
```

## API Endpoint Testing
```
How can I test the new beta coefficient API endpoints? I want to verify that /api/beta/summary/ and /api/beta/timeseries/{ticker}/ are working correctly.
```

## Data Import Issues
```
I'm having trouble importing beta coefficient data using the management command. The error is: [paste error]. How do I debug CSV import issues?
```

## Authentication Problems
```
My frontend can't authenticate with the Django backend. I'm getting CORS errors and authentication failures. How do I fix the session authentication?
```

## Performance Optimization
```
My beta coefficient API endpoints are running slowly when I have lots of data. What are some optimization strategies for the Django queries?
```

## Model Relationships
```
Can you explain the relationship between BetaRealized, ForecastEvaluation, and the existing Stock models? How should I structure my queries?
```

## Debugging Views
```
My BetaCoefficientSummaryView is returning empty results. How do I debug Django views and check what SQL queries are being generated?
```

## Environment Setup
```
I'm switching between development and production environments. What environment variables and settings should I configure for the beta forecasting backend?
```

## Custom Management Commands
```
How do I create additional management commands for the beta coefficient pipeline? I want to add scheduled tasks and data validation commands.
```