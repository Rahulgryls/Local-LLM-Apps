/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // LAKO brand palette — bank-appropriate dark blue
        'lako-blue':      '#1e3a5f',
        'lako-blue-light':'#2d5a8e',
        'lako-accent':    '#00a8e8',
      },
    },
  },
  plugins: [],
}
