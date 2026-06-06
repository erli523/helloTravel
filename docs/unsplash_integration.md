# Unsplash Image Integration

The project uses Unsplash as a direct service adapter instead of an Agent tool.
Image search is a deterministic enrichment step: after the trip plan is
generated, missing attraction images are filled with Unsplash photo URLs.

## Flow

1. `POST /api/travel/plans` receives a `TravelPlanRequest`.
2. `PlannerService` asks `TripPlannerAgent` to generate the validated `TripPlan`.
3. `TripImageService` scans every attraction.
4. If an attraction has no `image_url`, it calls `UnsplashService.get_photo_url()`.
5. `UnsplashService` queries `GET https://api.unsplash.com/search/photos`.
6. The first photo URL is written back to `attraction.image_url`.

## Configuration

Set these values in `backend/.env`:

```env
UNSPLASH_ENABLED=true
UNSPLASH_ACCESS_KEY=your-unsplash-access-key
UNSPLASH_BASE_URL=https://api.unsplash.com
UNSPLASH_TIMEOUT=10
UNSPLASH_PER_PAGE=1
```

If `UNSPLASH_ACCESS_KEY` is missing, the service returns an empty result and the
travel planning API still works.

## API Checks

Check integration status:

```bash
curl http://127.0.0.1:8000/api/travel/integrations
```

Search images directly:

```bash
curl "http://127.0.0.1:8000/api/travel/images/search?query=Beijing&per_page=3"
```

## Source Map

- `backend/app/services/unsplash_service.py`
- `backend/app/services/trip_image_service.py`
- `backend/app/services/planner_service.py`
- `backend/app/api/travel.py`
