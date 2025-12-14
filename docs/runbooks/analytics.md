# Analytics (Umami)

Floodmap loads Umami in production.

## Config location
- `src/web/index.html` injects the Umami script at runtime.
  - Defaults to disabled on `localhost` / `127.0.0.1`

## Query flags
- Disable: `?no_analytics=1`
- Force enable on localhost (for testing): `?analytics=1`
