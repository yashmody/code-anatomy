<template>
	<private-view title="Media Upload">
		<template #navigation>
			<v-list nav>
				<v-list-item :active="tab === 'upload'" clickable @click="tab = 'upload'">
					<v-list-item-icon><v-icon name="cloud_upload" /></v-list-item-icon>
					<v-list-item-content>Upload</v-list-item-content>
				</v-list-item>
				<v-list-item :active="tab === 'browse'" clickable @click="tab = 'browse'">
					<v-list-item-icon><v-icon name="perm_media" /></v-list-item-icon>
					<v-list-item-content>Browse</v-list-item-content>
				</v-list-item>
			</v-list>
		</template>

		<div class="media-upload-module">
			<div class="api-base">
				<v-input v-model="apiBase" placeholder="(same origin)" :nullable="false">
					<template #prepend><v-icon name="dns" small /></template>
				</v-input>
				<small class="muted">
					FastAPI base URL. Leave blank in production — the admin and the API share one
					origin behind Apache. For local dev set <code>http://localhost:8000</code>.
				</small>
			</div>

			<upload-panel v-if="tab === 'upload'" :api-base="apiBase" />
			<browse-panel v-else :api-base="apiBase" />
		</div>
	</private-view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import UploadPanel from './components/upload-panel.vue';
import BrowsePanel from './components/browse-panel.vue';

const STORAGE_KEY = 'mediaUploadApiBase';

const tab = ref<'upload' | 'browse'>('upload');
const apiBase = ref<string>(localStorage.getItem(STORAGE_KEY) ?? '');

// Persist the base URL so a dev only types it once. Empty = same origin (prod).
watch(apiBase, (value) => {
	if (value) localStorage.setItem(STORAGE_KEY, value);
	else localStorage.removeItem(STORAGE_KEY);
});
</script>

<style scoped>
.media-upload-module {
	padding: 0 var(--content-padding, 32px) var(--content-padding-bottom, 32px);
	max-width: 1024px;
}

.api-base {
	margin-bottom: 32px;
}

.api-base small {
	display: block;
	margin-top: 6px;
}

.muted {
	color: var(--theme--foreground-subdued, var(--foreground-subdued, #a2b5cd));
}

code {
	font-family: var(--theme--fonts--monospace--font-family, monospace);
	font-size: 0.9em;
}
</style>
