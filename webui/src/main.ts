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
      light: {
        dark: false,
        colors: {
          primary: '#4F46E5', secondary: '#64748B', surface: '#FFFFFF',
          background: '#F5F6FA', 'on-surface': '#202B40',
          success: '#208463', warning: '#A66A12', error: '#CC4055', info: '#287DB0'
        }
      },
      dark: {
        dark: true,
        colors: {
          primary: '#ACA7FF', secondary: '#A4B2CB', surface: '#1A2233',
          background: '#111827', 'on-surface': '#E5EAF4',
          success: '#6DD6AC', warning: '#F2C16B', error: '#FF8E9D', info: '#82C8EE'
        }
      }
    }
  },
  icons: { defaultSet: 'mdi', aliases, sets: { mdi } },
  defaults: {
    VCard: { rounded: 'lg', elevation: 0 },
    VBtn: { rounded: 'lg', elevation: 0 },
    VTextField: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VSelect: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VAutocomplete: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VCombobox: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VTextarea: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VNumberInput: { variant: 'outlined', density: 'comfortable', color: 'primary' }
  }
});

createApp(App).use(vuetify).use(router).mount('#app');
