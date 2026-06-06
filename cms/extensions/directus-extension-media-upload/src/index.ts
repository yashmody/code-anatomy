import { defineModule } from '@directus/extensions-sdk';
import ModuleComponent from './module.vue';

// Full-page admin screen. The bytes never touch Directus storage: the upload
// panel POSTs the file to FastAPI `POST /api/media/upload` (same origin in prod
// via Apache; cross-origin in dev), which writes it to a Postgres large object
// and inserts a `media_assets` row. The browse panel reads that metadata back
// through Directus and previews the bytes from FastAPI `/media/*`.
export default defineModule({
	id: 'media-upload',
	name: 'Media Upload',
	icon: 'cloud_upload',
	routes: [
		{
			path: '',
			component: ModuleComponent,
		},
	],
});
