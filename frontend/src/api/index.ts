// The one switch: swap this import for `./productionApi` once a real CAUSA
// HTTP API exists. Every page/hook imports data functions from `@/api`,
// never from `@/api/demoAdapter` directly, so the swap is a one-line change.
export * from './demoAdapter'
