import legacyPlugin from '@vitejs/plugin-legacy'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import mkcert from 'vite-plugin-mkcert'
import { join } from 'path'

// server of your OpenAvatarChat
// if you are not use localhost, you need to start https
const serverIP = 'localhost'
const serverPort = process.env.VITE_BACKEND_PORT || '8282'

// https://vitejs.dev/config/
export default defineConfig({
  base: './',
  build: {
    rollupOptions: {
      output: {
        entryFileNames: `assets/[name].js`,
        chunkFileNames: `assets/[name].js`,
        assetFileNames: `assets/[name].[ext]`,
      },
    },
  },
  server: {
    // host: '0.0.0.0',
    // https: true,
    // port: 443,
    proxy: {
      '/api': {
        target: `http://${serverIP}:${serverPort}`,
        changeOrigin: true,
        secure: false,
      },
      '/download': {
        target: `http://${serverIP}:${serverPort}`,
        changeOrigin: true,
        secure: false,
      },
      '/openavatarchat': {
        target: `http://${serverIP}:${serverPort}`,
        changeOrigin: true,
        secure: false,
      },
      '/webrtc': {
        target: `http://${serverIP}:${serverPort}`,
        changeOrigin: true,
        secure: false,
      },
      '/ws': {
        target: `ws://${serverIP}:${serverPort}`,
        ws: true,
        rewriteWsOrigin: true,
        secure: false,
      },
    },
  },
  plugins: [
    vue(),
    // 本地开发如果需要https才能走通接口的话，则需要开启mkcert,并且开启mkcert需要sudo权限
    // mkcert({
    //   source: 'coding'
    // }),
    legacyPlugin({
      modernPolyfills: true,
    }),
  ],
  resolve: {
    alias: {
      '@': join(__dirname, 'src'),
    },
  },
})
