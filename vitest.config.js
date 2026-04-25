// Vitest config for the MTG bot UI's JS unit tests.
//
// app.js is shipped as a classic <script> (no module system). Tests load it
// in a jsdom environment with a fixture document mirroring the IDs the
// script expects, and call the resulting global functions directly. See
// tests-js/setup.js for the loader.

import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests-js/**/*.test.js'],
    globals: false,
    reporters: ['default'],
  },
});
