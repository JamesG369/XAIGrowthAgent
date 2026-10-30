# XAIGrowthAgent

`index.html` is a dashboard that polls `twitter-stats.php` for X account metrics.

## Configuration

`twitter-stats.php` reads its credentials from environment variables on the host:

| Variable         | Required | Description                                             |
|------------------|----------|---------------------------------------------------------|
| `X_BEARER_TOKEN` | yes      | X/Twitter API v2 bearer token (from the X developer portal) |
| `X_USER_ID`      | no       | Numeric X user ID to report on (defaults to `2036579154360188928`) |

If `X_BEARER_TOKEN` is missing, the endpoint returns HTTP 500 with `{"error": "X_BEARER_TOKEN not set"}`.

Examples:

- Apache (`.htaccess` or vhost): `SetEnv X_BEARER_TOKEN your-token-here`
- PHP-FPM pool config: `env[X_BEARER_TOKEN] = your-token-here`
- Shared hosting: use the control panel's environment-variable settings.

Never commit the token to this repository.
