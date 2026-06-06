<template>
	<div class="upload-panel">
		<div
			class="dropzone"
			:class="{ over: dragOver, hasfile: !!file }"
			@click="picker?.click()"
			@dragover.prevent="dragOver = true"
			@dragleave.prevent="dragOver = false"
			@drop.prevent="onDrop"
		>
			<input
				ref="picker"
				type="file"
				class="hidden-input"
				accept="image/*,video/*"
				@change="onPick"
			/>
			<v-icon name="cloud_upload" x-large />
			<p v-if="!file" class="hint">Drop an image or video here, or click to choose a file.</p>
			<p v-else class="file-meta">
				<strong>{{ file.name }}</strong>
				<span class="muted">{{ prettyType }} · {{ prettySize }}</span>
			</p>
		</div>

		<div class="actions">
			<v-button :loading="uploading" :disabled="!file || uploading" @click="upload">
				<v-icon name="upload" left /> Upload
			</v-button>
			<v-button v-if="file && !uploading" secondary @click="reset">Clear</v-button>
		</div>

		<v-progress-linear v-if="uploading" :value="progress" rounded class="progress" />

		<v-notice v-if="error" type="danger" class="result-notice">
			<div v-html="error" />
		</v-notice>

		<template v-if="result">
			<v-notice type="success" class="result-notice">
				<div class="asset-line">
					<span>Uploaded. Asset id <code class="asset-id">{{ result.asset_id }}</code></span>
					<v-button x-small secondary @click="copyId">Copy</v-button>
				</div>
			</v-notice>

			<div class="preview">
				<video v-if="isVideo" :src="previewUrl" controls preload="metadata" />
				<img v-else :src="previewUrl" :alt="result.asset_id" />
				<small class="muted">Streamed by FastAPI from a Postgres large object — <code>{{ previewUrl }}</code></small>
			</div>
		</template>
	</div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';

const props = defineProps<{ apiBase: string }>();

interface UploadResult {
	status: string;
	asset_id: string;
	url: string;
}

const picker = ref<HTMLInputElement | null>(null);
const file = ref<File | null>(null);
const dragOver = ref(false);
const uploading = ref(false);
const progress = ref(0);
const result = ref<UploadResult | null>(null);
const error = ref<string | null>(null);

// Trim a trailing slash so `${base}/api/...` never doubles up. Empty = same origin.
const base = computed(() => props.apiBase.replace(/\/+$/, ''));

const isVideo = computed(() => {
	if (result.value) return result.value.url.includes('/media/video/');
	return file.value?.type.startsWith('video/') ?? false;
});

const previewUrl = computed(() => (result.value ? base.value + result.value.url : ''));
const prettyType = computed(() => file.value?.type || 'unknown type');
const prettySize = computed(() => formatBytes(file.value?.size ?? 0));

function formatBytes(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function onPick(event: Event) {
	const input = event.target as HTMLInputElement;
	setFile(input.files?.[0] ?? null);
}

function onDrop(event: DragEvent) {
	dragOver.value = false;
	setFile(event.dataTransfer?.files?.[0] ?? null);
}

function setFile(next: File | null) {
	file.value = next;
	result.value = null;
	error.value = null;
}

function reset() {
	setFile(null);
	progress.value = 0;
	if (picker.value) picker.value.value = '';
}

function copyId() {
	if (result.value) navigator.clipboard?.writeText(result.value.asset_id);
}

// Map the FastAPI status onto guidance. The cross-plane coupling (401/403) is
// the non-obvious one: this module reuses the learner-plane session, which is
// separate from the Directus staff login.
function describeError(status: number, detail: string): string {
	switch (status) {
		case 0:
			return (
				`Could not reach the API${base.value ? ` at <code>${base.value}</code>` : ''}. ` +
				`If you are running locally, set the FastAPI base URL above to ` +
				`<code>http://localhost:8000</code> and ensure the backend <code>CORS_ORIGINS</code> ` +
				`includes <code>http://localhost:8055</code>.`
			);
		case 401:
			return (
				`Not signed in to the application session. This upload reuses your ` +
				`<code>aoc_session</code> cookie — open the app, sign in with the same browser, then retry.`
			);
		case 403:
			return (
				`Your account lacks the <code>media.upload</code> permission. It is granted to the ` +
				`<code>content_author</code> and <code>feed_contributor</code> roles in the application user table.`
			);
		case 413:
			return detail || 'The file exceeds the configured size limit.';
		case 400:
			return detail || 'Unsupported file format, or the file header did not match its type.';
		default:
			return detail ? `Upload failed (${status}): ${detail}` : `Upload failed (HTTP ${status}).`;
	}
}

function upload() {
	if (!file.value) return;
	uploading.value = true;
	progress.value = 0;
	error.value = null;
	result.value = null;

	const form = new FormData();
	// Field name MUST be `file` — matches the FastAPI UploadFile parameter.
	form.append('file', file.value);

	const xhr = new XMLHttpRequest();
	xhr.open('POST', `${base.value}/api/media/upload`);
	// Send the aoc_session cookie. Same-origin in prod; needs CORS in dev.
	xhr.withCredentials = true;

	xhr.upload.onprogress = (event) => {
		if (event.lengthComputable) progress.value = Math.round((event.loaded / event.total) * 100);
	};

	xhr.onload = () => {
		uploading.value = false;
		let body: any = null;
		let detail = '';
		try {
			body = JSON.parse(xhr.responseText);
			detail = body?.detail ?? '';
		} catch {
			/* non-JSON error body */
		}
		if (xhr.status >= 200 && xhr.status < 300 && body?.asset_id) {
			result.value = body as UploadResult;
		} else {
			error.value = describeError(xhr.status, detail);
		}
	};

	xhr.onerror = () => {
		uploading.value = false;
		error.value = describeError(0, '');
	};

	xhr.send(form);
}
</script>

<style scoped>
.upload-panel {
	display: flex;
	flex-direction: column;
	gap: 20px;
}

.dropzone {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 12px;
	min-height: 200px;
	padding: 32px;
	text-align: center;
	cursor: pointer;
	border: 2px dashed var(--theme--border-color, var(--border-normal, #d3dae4));
	border-radius: var(--theme--border-radius, 8px);
	background-color: var(--theme--background-subdued, var(--background-subdued, #f7f9fc));
	color: var(--theme--foreground-subdued, var(--foreground-subdued, #a2b5cd));
	transition: border-color var(--fast, 150ms), background-color var(--fast, 150ms);
}

.dropzone.over,
.dropzone:hover {
	border-color: var(--theme--primary, var(--primary, #6644ff));
	color: var(--theme--primary, var(--primary, #6644ff));
}

.dropzone.hasfile {
	border-style: solid;
	color: var(--theme--foreground, var(--foreground-normal, #4f5464));
}

.hidden-input {
	display: none;
}

.file-meta {
	display: flex;
	flex-direction: column;
	gap: 4px;
}

.actions {
	display: flex;
	gap: 12px;
}

.progress {
	margin: 4px 0;
}

.result-notice {
	word-break: break-word;
}

.asset-line {
	display: flex;
	align-items: center;
	gap: 12px;
	flex-wrap: wrap;
}

.asset-id {
	font-family: var(--theme--fonts--monospace--font-family, monospace);
}

.preview {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.preview img,
.preview video {
	max-width: 100%;
	max-height: 480px;
	border-radius: var(--theme--border-radius, 8px);
	background-color: var(--theme--background-subdued, #f0f4f9);
}

.muted {
	color: var(--theme--foreground-subdued, var(--foreground-subdued, #a2b5cd));
}

code {
	font-family: var(--theme--fonts--monospace--font-family, monospace);
	font-size: 0.9em;
}
</style>
