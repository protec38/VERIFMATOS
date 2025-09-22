/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        pcblue: '#0b4a87',
        pcorange: '#f39200'
      }
    }
  },
  plugins: []
}
