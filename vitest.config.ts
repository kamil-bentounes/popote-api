import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/db/**/*.test.ts', 'worker/test/**/*.test.ts'],
    exclude: ['node_modules/**', '.claude/**'],
    // Rejoue une fois une requête coupée par la passerelle locale (voir tests/db/helpers/fetch-reprise.ts).
    setupFiles: ['tests/db/helpers/installe-fetch-reprise.ts'],
    testTimeout: 30_000,
    hookTimeout: 60_000,
    fileParallelism: false,
  },
})
