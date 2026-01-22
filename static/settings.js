/**
 * Settings Modal Logic
 * Handles feeds, models, and export functionality
 */

// DOM Elements
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
const modalClose = document.getElementById('modal-close');
const tabBtns = document.querySelectorAll('.tab-btn');

// Feed elements
const csvUploadArea = document.getElementById('csv-upload-area');
const csvFileInput = document.getElementById('csv-file-input');
const csvInput = document.getElementById('csv-input');
const importCsvBtn = document.getElementById('import-csv-btn');
const importResult = document.getElementById('import-result');
const feedStats = document.getElementById('feed-stats');
const feedList = document.getElementById('feed-list');
const refreshFeedsBtn = document.getElementById('refresh-feeds-btn');
const refreshResult = document.getElementById('refresh-result');

// Model elements
const modelUploadArea = document.getElementById('model-upload-area');
const modelFileInput = document.getElementById('model-file-input');
const modelName = document.getElementById('model-name');
const uploadModelBtn = document.getElementById('upload-model-btn');
const modelUploadResult = document.getElementById('model-upload-result');
const modelStatus = document.getElementById('model-status');
const modelList = document.getElementById('model-list');

// Export elements
const exportBtn = document.getElementById('export-btn');
const exportStats = document.getElementById('export-stats');

// Import elements
const trainingUploadArea = document.getElementById('training-upload-area');
const trainingFileInput = document.getElementById('training-file-input');
const importTrainingBtn = document.getElementById('import-training-btn');
const trainingImportResult = document.getElementById('training-import-result');

// State
let selectedModelFile = null;
let selectedTrainingFile = null;

// =====================
// Modal Controls
// =====================

function openModal() {
    settingsModal.classList.add('active');
    document.body.style.overflow = 'hidden';
    loadFeedsTab();
}

function closeModal() {
    settingsModal.classList.remove('active');
    document.body.style.overflow = '';
}

settingsBtn.addEventListener('click', openModal);
modalClose.addEventListener('click', closeModal);
settingsModal.addEventListener('click', (e) => {
    if (e.target === settingsModal) closeModal();
});

// Close on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && settingsModal.classList.contains('active')) {
        closeModal();
    }
});

// =====================
// Tab Navigation
// =====================

tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tabId = btn.dataset.tab;

        // Update tab buttons
        tabBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
        document.getElementById(`tab-${tabId}`).classList.add('active');

        // Load tab data
        if (tabId === 'feeds') loadFeedsTab();
        else if (tabId === 'models') loadModelsTab();
        else if (tabId === 'export') loadExportTab();
    });
});

// =====================
// Feeds Tab
// =====================

async function loadFeedsTab() {
    feedStats.innerHTML = '<span>Loading...</span>';
    feedList.innerHTML = '<div class="loading-spinner"></div>';

    try {
        const response = await fetch('/api/feeds');

        // Check content type before parsing
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Server returned non-JSON response. Check server logs.');
        }

        const data = await response.json();

        // Handle error response
        if (data.error) {
            throw new Error(data.error);
        }

        // Update stats
        const stats = data.stats;
        feedStats.innerHTML = `
            <span class="feed-stat"><strong>${stats.total_feeds}</strong> feeds</span>
            <span class="feed-stat"><strong>${stats.active_feeds}</strong> active</span>
            <span class="feed-stat"><strong>${stats.total_entries}</strong> entries</span>
        `;

        // Update feed list
        if (data.feeds.length === 0) {
            feedList.innerHTML = '<p class="empty-message">No feeds yet. Import feeds above.</p>';
        } else {
            feedList.innerHTML = data.feeds.map(feed => `
                <div class="feed-item ${feed.active ? '' : 'inactive'}">
                    <div class="feed-info">
                        <div class="feed-name">${escapeHtml(feed.name)}</div>
                        <div class="feed-url">${escapeHtml(feed.url)}</div>
                        <div class="feed-meta">${feed.entry_count} entries</div>
                    </div>
                    <div class="feed-actions">
                        <button class="btn-icon-small ${feed.active ? '' : 'inactive'}"
                                onclick="toggleFeed(${feed.id})"
                                title="${feed.active ? 'Disable' : 'Enable'}">
                            ${feed.active ? '✓' : '○'}
                        </button>
                        <button class="btn-icon-small delete"
                                onclick="deleteFeed(${feed.id}, '${escapeHtml(feed.name)}')"
                                title="Delete">
                            ×
                        </button>
                    </div>
                </div>
            `).join('');
        }
    } catch (err) {
        feedStats.innerHTML = '<span class="error">Error loading feeds</span>';
        feedList.innerHTML = `<p class="error">${err.message}</p>`;
    }
}

// CSV Upload via drag & drop
csvUploadArea.addEventListener('click', () => csvFileInput.click());
csvUploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    csvUploadArea.classList.add('dragover');
});
csvUploadArea.addEventListener('dragleave', () => {
    csvUploadArea.classList.remove('dragover');
});
csvUploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    csvUploadArea.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.csv')) {
        handleCsvFile(file);
    }
});
csvFileInput.addEventListener('change', () => {
    if (csvFileInput.files[0]) {
        handleCsvFile(csvFileInput.files[0]);
    }
});

function handleCsvFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        csvInput.value = e.target.result;
    };
    reader.readAsText(file);
}

// Import CSV
importCsvBtn.addEventListener('click', async () => {
    const content = csvInput.value.trim();
    if (!content) {
        showImportResult('Please enter CSV content or upload a file', 'error');
        return;
    }

    importCsvBtn.disabled = true;
    importCsvBtn.textContent = 'Importing...';

    try {
        const response = await fetch('/api/feeds', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ csv_content: content })
        });

        // Check content type before parsing
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Server returned non-JSON response. Check CSV format.');
        }

        const data = await response.json();

        if (data.success) {
            showImportResult(
                `Added ${data.feeds_added} feeds (${data.feeds_skipped} skipped)`,
                'success'
            );
            csvInput.value = '';
            loadFeedsTab();
        } else {
            showImportResult(data.error || data.errors?.join(', ') || 'Import failed', 'error');
        }
    } catch (err) {
        // Handle JSON parse errors specifically
        if (err instanceof SyntaxError) {
            showImportResult('Server error: Invalid response format', 'error');
        } else {
            showImportResult(err.message, 'error');
        }
    } finally {
        importCsvBtn.disabled = false;
        importCsvBtn.textContent = 'Import Feeds';
    }
});

function showImportResult(message, type) {
    importResult.textContent = message;
    importResult.className = `import-result ${type}`;
    importResult.style.display = 'block';
    setTimeout(() => { importResult.style.display = 'none'; }, 5000);
}

async function toggleFeed(feedId) {
    try {
        await fetch(`/api/feeds/${feedId}/toggle`, { method: 'POST' });
        loadFeedsTab();
    } catch (err) {
        alert('Error toggling feed: ' + err.message);
    }
}

async function deleteFeed(feedId, feedName) {
    if (!confirm(`Delete "${feedName}" and all its entries?`)) return;

    try {
        const response = await fetch(`/api/feeds/${feedId}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.success) {
            loadFeedsTab();
        } else {
            alert(data.error || 'Delete failed');
        }
    } catch (err) {
        alert('Error deleting feed: ' + err.message);
    }
}

// Refresh feeds with SSE progress
refreshFeedsBtn.addEventListener('click', () => {
    refreshFeedsBtn.disabled = true;
    refreshFeedsBtn.innerHTML = '<span class="btn-icon">⏳</span> Refreshing...';
    showRefreshResult('Connecting...', 'info');

    const eventSource = new EventSource('/api/feeds/refresh');

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'progress') {
            showRefreshResult(data.message, 'info');
        } else if (data.type === 'complete') {
            eventSource.close();
            showRefreshResult(
                `Fetched ${data.feeds_successful}/${data.feeds_fetched} feeds, ${data.entries_new} new articles`,
                'success'
            );
            loadFeedsTab();
            refreshFeedsBtn.disabled = false;
            refreshFeedsBtn.innerHTML = '<span class="btn-icon">🔄</span> Refresh Feeds';
        } else if (data.type === 'error') {
            eventSource.close();
            showRefreshResult('Error: ' + data.error, 'error');
            refreshFeedsBtn.disabled = false;
            refreshFeedsBtn.innerHTML = '<span class="btn-icon">🔄</span> Refresh Feeds';
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
        showRefreshResult('Connection error during refresh', 'error');
        refreshFeedsBtn.disabled = false;
        refreshFeedsBtn.innerHTML = '<span class="btn-icon">🔄</span> Refresh Feeds';
    };
});

function showRefreshResult(message, type) {
    refreshResult.textContent = message;
    refreshResult.className = `refresh-result ${type}`;
    refreshResult.style.display = 'block';
    if (type !== 'info') {
        setTimeout(() => { refreshResult.style.display = 'none'; }, 10000);
    }
}

// =====================
// Models Tab
// =====================

async function loadModelsTab() {
    modelStatus.innerHTML = '<div class="loading-spinner"></div>';
    modelList.innerHTML = '<div class="loading-spinner"></div>';

    try {
        const response = await fetch('/api/models');
        const data = await response.json();

        // Update current model status
        if (data.using_default) {
            modelStatus.innerHTML = `
                <div class="status-card default">
                    <div class="status-icon">🤖</div>
                    <div class="status-info">
                        <div class="status-title">Default Model (Hybrid RF)</div>
                        <div class="status-detail">No custom model active</div>
                    </div>
                </div>
            `;
        } else if (data.active_model) {
            const model = data.active_model;
            const metadata = typeof model.metadata === 'string' ?
                JSON.parse(model.metadata) : model.metadata;
            modelStatus.innerHTML = `
                <div class="status-card active">
                    <div class="status-icon">✓</div>
                    <div class="status-info">
                        <div class="status-title">${escapeHtml(model.name)}</div>
                        <div class="status-detail">
                            ${metadata?.model_type || 'Unknown'} |
                            ROC-AUC: ${metadata?.roc_auc?.toFixed(4) || 'N/A'}
                        </div>
                    </div>
                </div>
            `;
        }

        // Update model list
        if (data.models.length === 0) {
            modelList.innerHTML = '<p class="empty-message">No uploaded models. Upload a model above.</p>';
        } else {
            modelList.innerHTML = data.models.map(model => {
                const metadata = model.metadata || {};
                return `
                    <div class="model-item ${model.is_active ? 'active' : ''}">
                        <div class="model-info">
                            <div class="model-name">${escapeHtml(model.name)}</div>
                            <div class="model-meta">
                                ${metadata.model_type || 'Unknown'} |
                                ROC-AUC: ${metadata.roc_auc?.toFixed(4) || 'N/A'} |
                                ${metadata.n_samples || '?'} samples
                            </div>
                        </div>
                        <div class="model-actions">
                            ${model.is_active ?
                                '<span class="active-badge">Active</span>' :
                                `<button class="btn btn-small" onclick="activateModel(${model.id})">Activate</button>
                                 <button class="btn-icon-small delete" onclick="deleteModel(${model.id}, '${escapeHtml(model.name)}')" title="Delete">×</button>`
                            }
                        </div>
                    </div>
                `;
            }).join('');
        }
    } catch (err) {
        modelStatus.innerHTML = `<p class="error">${err.message}</p>`;
        modelList.innerHTML = '';
    }
}

// Model Upload via drag & drop
modelUploadArea.addEventListener('click', () => modelFileInput.click());
modelUploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    modelUploadArea.classList.add('dragover');
});
modelUploadArea.addEventListener('dragleave', () => {
    modelUploadArea.classList.remove('dragover');
});
modelUploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    modelUploadArea.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.pkl')) {
        handleModelFile(file);
    }
});
modelFileInput.addEventListener('change', () => {
    if (modelFileInput.files[0]) {
        handleModelFile(modelFileInput.files[0]);
    }
});

function handleModelFile(file) {
    selectedModelFile = file;
    modelUploadArea.innerHTML = `
        <div class="upload-icon">✓</div>
        <p>${escapeHtml(file.name)}</p>
        <p class="upload-hint">${(file.size / 1024 / 1024).toFixed(2)} MB</p>
    `;
    uploadModelBtn.disabled = false;

    // Auto-fill name if empty
    if (!modelName.value) {
        modelName.value = file.name.replace('.pkl', '');
    }
}

uploadModelBtn.addEventListener('click', async () => {
    if (!selectedModelFile) return;

    const name = modelName.value.trim() || selectedModelFile.name.replace('.pkl', '');
    uploadModelBtn.disabled = true;
    uploadModelBtn.textContent = 'Uploading...';

    try {
        const formData = new FormData();
        formData.append('file', selectedModelFile);
        formData.append('name', name);

        const response = await fetch('/api/models', {
            method: 'POST',
            body: formData
        });

        // Check content type before parsing
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Server returned non-JSON response. Check server logs.');
        }

        const data = await response.json();

        if (data.success) {
            showModelResult(`Model "${name}" uploaded successfully!`, 'success');
            selectedModelFile = null;
            modelFileInput.value = '';
            modelName.value = '';
            modelUploadArea.innerHTML = `
                <div class="upload-icon">🤖</div>
                <p>Drag & drop .pkl file here</p>
                <p class="upload-hint">or click to browse</p>
            `;
            loadModelsTab();
        } else {
            showModelResult(data.error || 'Upload failed', 'error');
        }
    } catch (err) {
        // Handle JSON parse errors specifically
        if (err instanceof SyntaxError) {
            showModelResult('Server error: Invalid response format', 'error');
        } else {
            showModelResult(err.message, 'error');
        }
    } finally {
        uploadModelBtn.disabled = !selectedModelFile;
        uploadModelBtn.textContent = 'Upload Model';
    }
});

function showModelResult(message, type) {
    modelUploadResult.textContent = message;
    modelUploadResult.className = `upload-result ${type}`;
    modelUploadResult.style.display = 'block';
    setTimeout(() => { modelUploadResult.style.display = 'none'; }, 5000);
}

async function activateModel(modelId) {
    try {
        const response = await fetch(`/api/models/${modelId}/activate`, { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            loadModelsTab();
        } else {
            alert(data.error || 'Activation failed');
        }
    } catch (err) {
        alert('Error activating model: ' + err.message);
    }
}

async function deleteModel(modelId, modelName) {
    if (!confirm(`Delete model "${modelName}"?`)) return;

    try {
        const response = await fetch(`/api/models/${modelId}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.success) {
            loadModelsTab();
        } else {
            alert(data.error || 'Delete failed');
        }
    } catch (err) {
        alert('Error deleting model: ' + err.message);
    }
}

// =====================
// Export Tab
// =====================

async function loadExportTab() {
    exportStats.innerHTML = '<div class="loading-spinner"></div>';

    try {
        const response = await fetch('/api/export/training-data/preview');
        const data = await response.json();

        const breakdown = data.vote_breakdown || {};
        exportStats.innerHTML = `
            <div class="export-stat-grid">
                <div class="export-stat">
                    <div class="export-stat-value">${data.total_samples}</div>
                    <div class="export-stat-label">Total Votes</div>
                </div>
                <div class="export-stat">
                    <div class="export-stat-value">${breakdown.like || 0}</div>
                    <div class="export-stat-label">Likes</div>
                </div>
                <div class="export-stat">
                    <div class="export-stat-value">${breakdown.neutral || 0}</div>
                    <div class="export-stat-label">Neutral</div>
                </div>
                <div class="export-stat">
                    <div class="export-stat-value">${breakdown.dislike || 0}</div>
                    <div class="export-stat-label">Dislikes</div>
                </div>
            </div>
        `;
    } catch (err) {
        exportStats.innerHTML = `<p class="error">${err.message}</p>`;
    }
}

exportBtn.addEventListener('click', () => {
    window.location.href = '/api/export/training-data';
});

// Training data import via drag & drop
trainingUploadArea.addEventListener('click', () => trainingFileInput.click());
trainingUploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    trainingUploadArea.classList.add('dragover');
});
trainingUploadArea.addEventListener('dragleave', () => {
    trainingUploadArea.classList.remove('dragover');
});
trainingUploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    trainingUploadArea.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.csv')) {
        handleTrainingFile(file);
    }
});
trainingFileInput.addEventListener('change', () => {
    if (trainingFileInput.files[0]) {
        handleTrainingFile(trainingFileInput.files[0]);
    }
});

function handleTrainingFile(file) {
    selectedTrainingFile = file;
    trainingUploadArea.innerHTML = `
        <div class="upload-icon">✓</div>
        <p>${escapeHtml(file.name)}</p>
        <p class="upload-hint">${(file.size / 1024).toFixed(1)} KB</p>
    `;
    importTrainingBtn.disabled = false;
}

importTrainingBtn.addEventListener('click', async () => {
    if (!selectedTrainingFile) return;

    importTrainingBtn.disabled = true;
    importTrainingBtn.textContent = 'Importing...';

    try {
        const formData = new FormData();
        formData.append('file', selectedTrainingFile);

        const response = await fetch('/api/import/training-data', {
            method: 'POST',
            body: formData
        });

        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Server returned non-JSON response. Check server logs.');
        }

        const data = await response.json();

        if (data.success) {
            showTrainingImportResult(
                `Imported ${data.votes_imported} votes (${data.entries_not_found} entries not found)`,
                'success'
            );
            selectedTrainingFile = null;
            trainingFileInput.value = '';
            trainingUploadArea.innerHTML = `
                <div class="upload-icon">📤</div>
                <p>Drag & drop training_data.csv here</p>
                <p class="upload-hint">or click to browse</p>
            `;
            loadExportTab();
        } else {
            showTrainingImportResult(data.error || 'Import failed', 'error');
        }
    } catch (err) {
        showTrainingImportResult(err.message, 'error');
    } finally {
        importTrainingBtn.disabled = !selectedTrainingFile;
        importTrainingBtn.textContent = 'Import Training Data';
    }
});

function showTrainingImportResult(message, type) {
    trainingImportResult.textContent = message;
    trainingImportResult.className = `upload-result ${type}`;
    trainingImportResult.style.display = 'block';
    setTimeout(() => { trainingImportResult.style.display = 'none'; }, 8000);
}

// =====================
// Utilities
// =====================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
