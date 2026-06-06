<template>
	<div class="browse-panel">
		<div class="browse-head">
			<p class="muted">
				Existing media — metadata read from Directus (the read-only <code>media_assets</code>
				binding), bytes streamed by FastAPI <code>/media/*</code>.
			</p>
			<v-button secondary small :loading="loading" @click="load">
				<v-icon name="refresh" left /> Refresh
			</v-button>
		</div>

		<v-notice v-if="error" type="warning">{{ error }}</v-notice>
		<v-notice v-else-if="!loading && assets.length === 0" type="info">
			No media assets yet. Upload one from the Upload tab.
		</v-notice>

		<div class="grid">
			<div v-for="asset in assets" :key="asset.id" class="asset-card">
				<div class="thumb">
					<video v-if="isVideo(asset)" :src="mediaUrl(asset)" controls preload="metadata" />
					<img v-else :src="mediaUrl(asset)" :alt="asset.filename" loading="lazy" />
				</div>
				<div class="asset-body">
					<strong class="filename" :title="asset.filename">{{ asset.filename }}</strong>
					<span class="muted">{{ asset.mime_type }} · {{ formatBytes(asset.size_bytes) }}</span>
					<code class="muted asset-id">{{ asset.id }}</code>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

interface MediaAsset {
	id: string;
	filename: string;
	mime_type: string;
	size_bytes: number;
	uploaded_at?: string;
}

const props = defineProps<{ apiBase: string }>();

// useApi() is the Directus axios instance — correct here: metadata reads go
// through Directus (read perm already granted to the staff roles). Only the
// preview bytes come from FastAPI.
const api = useApi();

const assets = ref<MediaAsset[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const base = computed(() => props.apiBase.replace(/\/+$/, ''));

function isVideo(asset: MediaAsset): boolean {
	return (asset.mime_type || '').startsWith('video/');
}

function mediaUrl(asset: MediaAsset): string {
	return `${base.value}/media/${isVideo(asset) ? 'video' : 'image'}/${asset.id}`;
}

function formatBytes(bytes: number): string {
	if (!bytes) return '0 B';
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function load() {
	loading.value = true;
	error.value = null;
	try {
		const res = await api.get('/items/media_assets', {
			params: {
				fields: ['id', 'filename', 'mime_type', 'size_bytes', 'uploaded_at'],
				sort: ['-uploaded_at'],
				limit: 50,
			},
		});
		assets.value = res.data?.data ?? [];
	} catch (err: any) {
		error.value =
			err?.response?.data?.errors?.[0]?.message ||
			'Could not load media metadata from Directus.';
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>

<style scoped>
.browse-panel {
	display: flex;
	flex-direction: column;
	gap: 20px;
}

.browse-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 16px;
}

.grid {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
	gap: 16px;
}

.asset-card {
	display: flex;
	flex-direction: column;
	border: 1px solid var(--theme--border-color, var(--border-normal, #d3dae4));
	border-radius: var(--theme--border-radius, 8px);
	overflow: hidden;
	background-color: var(--theme--background, var(--background-page, #fff));
}

.thumb {
	aspect-ratio: 4 / 3;
	background-color: var(--theme--background-subdued, var(--background-subdued, #f0f4f9));
	display: flex;
	align-items: center;
	justify-content: center;
	overflow: hidden;
}

.thumb img,
.thumb video {
	width: 100%;
	height: 100%;
	object-fit: contain;
}

.asset-body {
	display: flex;
	flex-direction: column;
	gap: 4px;
	padding: 12px;
}

.filename {
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.asset-id {
	font-size: 0.8em;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.muted {
	color: var(--theme--foreground-subdued, var(--foreground-subdued, #a2b5cd));
}

code {
	font-family: var(--theme--fonts--monospace--font-family, monospace);
}
</style>
