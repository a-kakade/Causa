// The one switch: `causa/api/` (FastAPI over the real Step 1-9 engines) now
// exists, so this points at `./productionApi`. Every page/hook imports data
// functions from `@/api`, never from `@/api/demoAdapter` directly, so this
// swap (and any future rollback for offline/demo use) is a one-line change.
export * from './productionApi'
