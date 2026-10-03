import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import installTooltip from './utils/tooltip.js'

installTooltip()

createApp(App).mount('#app')

