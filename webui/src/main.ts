import { createApp } from 'vue';
import { createVuetify } from 'vuetify';
import { aliases, mdi } from 'vuetify/iconsets/mdi';
import 'vuetify/styles';
import '@mdi/font/css/materialdesignicons.css';

import App from './App.vue';
import router from './router';
import '@/styles/main.css';

const storedTheme = localStorage.getItem('acgimg-theme');
const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
const vuetify = createVuetify({
  theme: {
    defaultTheme: storedTheme === 'dark' || storedTheme === 'light' ? storedTheme : systemDark ? 'dark' : 'light',
    themes: {
      light: { dark: false, colors: { primary: '#6750A4', secondary: '#625B71', surface: '#FFFBFE', background: '#FFFBFE' } },
      dark: { dark: true, colors: { primary: '#D0BCFF', secondary: '#CCC2DC', surface: '#141218', background: '#141218' } }
    }
  },
  icons: { defaultSet: 'mdi', aliases, sets: { mdi } }
});

createApp(App).use(vuetify).use(router).mount('#app');
