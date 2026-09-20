import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { SessionProvider } from './session';
import '@fontsource-variable/dm-sans';
import '@fontsource-variable/space-grotesk';
import './styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('Application root missing.');
createRoot(root).render(<StrictMode><BrowserRouter><SessionProvider><App /></SessionProvider></BrowserRouter></StrictMode>);
