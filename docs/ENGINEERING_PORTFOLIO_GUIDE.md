# Capital Compass: Engineering Portfolio Guide

## Project and team

Capital Compass is a university team project for analyzing and forecasting equity beta coefficients, with a Django REST Framework backend and a Next.js frontend. Refer to the [README](../README.md) for the original team roster and feature documentation. Claims of individual authorship should be supported by the commit or pull-request history.

## Architecture overview

```text
Web browser (Next.js / React)
      |
      | HTTP requests / JWT authentication
      v
Django REST Framework API
      |              |
      v              v
PostgreSQL       Forecasting / analysis code
      |              |
      +------> Results and visualizations
```

The diagram is conceptual. Consult the source for actual request handling, scheduling and storage mechanisms.

| Concern | Source |
| --- | --- |
| Django server | [backend](../backend) |
| API/application implementation | [backend/webapp](../backend/webapp) |
| Frontend | [frontend](../frontend) |
| Existing tests and configuration | [backend/pytest.ini](../backend/pytest.ini) and repository tests |
| Project architecture and user workflows | [README](../README.md) |

## Important modeling distinction

**Beta is market exposure, not a test of mean reversion.** In a market-model regression, a positive beta usually indicates positive sensitivity to benchmark returns, while a negative beta indicates inverse sensitivity. Momentum and mean reversion concern time-series dynamics and require separate measures or tests. Consequently, interpreting positive beta as momentum or negative beta as mean reversion is not generally valid.

## Technical questions for maintainers and reviewers

- How do large spreadsheet uploads avoid overloading request handlers?
- Are long-running forecasts executed in separate workers or in-process, and how do they survive restarts?
- How are uploads validated, stored, and scoped to an authenticated user?
- Which parts of model training and cross-validation prevent look-ahead bias?
- How are test coverage, failures, compute time, and resource costs measured?

These are **verification questions**, not claims that each mechanism is implemented.

## Engineering improvements to prioritize

1. Document request and worker/job state transitions, with observed behavior and failure cases.
2. Add executable tests for malformed uploads, authorization, and retry/idempotency behavior as applicable.
3. Validate the statistical interpretation and all README claims against model code and outputs.
4. Replace raw-IP HTTP demo references with a verified HTTPS deployment link if a current deployment exists, or identify them as historical.
5. Record actual benchmarks for computation time, file size and runtime resources.

## Portfolio integrity

Avoid stating that you alone developed all of this team project. Specify the components you owned and refer to individual commits/PRs where possible. A strong case study makes your contribution verifiable.
