/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        panel: "#121a24",
        ink: "#071019",
        cyan: "#22d3ee",
        amber: "#fbbf24"
      }
    }
  },
  plugins: []
};

