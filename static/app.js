class PreloadQueue {
    constructor(batchSize = 4, minQueueSize = 2) {
        this.queue = [];
        this.batchSize = batchSize;
        this.minQueueSize = minQueueSize;
        this.isFetching = false;
    }

    getQueuedIds() {
        return this.queue.map((post) => post.id);
    }

    async fetchBatch(additionalExcludeIds = []) {
        if (this.isFetching) {
            return;
        }

        this.isFetching = true;

        try {
            const excludeIds = [...this.getQueuedIds(), ...additionalExcludeIds];
            const url = `/api/posts/batch?count=${this.batchSize}&exclude=${excludeIds.join(',')}`;
            const response = await fetch(url);

            if (!response.ok) {
                return;
            }

            const data = await response.json();
            if (Array.isArray(data.posts) && data.posts.length) {
                this.queue.push(...data.posts);
            }
        } catch (error) {
            console.error('Failed to preload posts:', error);
        } finally {
            this.isFetching = false;
        }
    }

    getNext() {
        if (!this.queue.length) {
            return null;
        }

        const post = this.queue.shift();

        if (this.queue.length < this.minQueueSize && !this.isFetching) {
            this.fetchBatch([post.id]);
        }

        return post;
    }

    peek() {
        return this.queue[0] || null;
    }

    size() {
        return this.queue.length;
    }
}

class RSSSwipr {
    constructor() {
        this.currentPost = null;
        this.startTime = null;
        this.isVoting = false;
        this.viewMode = 'full';
        this.viewModeKey = 'rss_swipr_view_mode';

        this.dragStartX = 0;
        this.dragStartY = 0;
        this.lastDeltaX = 0;
        this.lastDeltaY = 0;
        this.isDragging = false;
        this.hasMoved = false;
        this.touchStartTime = 0;
        this.activePointerId = null;

        this.ogCache = new Map();
        this.toastTimer = null;
        this.browserUrl = '';
        this.linkOpenLockedUntil = 0;

        this.preloadQueue = new PreloadQueue(4, 2);

        this.init();
    }

    async init() {
        this.bindElements();
        this.initViewMode();
        this.attachEventListeners();

        this.showLoading(true);

        try {
            await Promise.all([
                this.loadStats(),
                this.preloadQueue.fetchBatch()
            ]);
            this.displayNextPost();
        } catch (error) {
            console.error('Initialization failed:', error);
            this.showLoading(false);
            this.showToast('初始化失败，请刷新后重试');
        }
    }

    bindElements() {
        this.card = document.getElementById('card');
        this.cardImg = document.getElementById('card-img');
        this.cardTitle = document.getElementById('card-title');
        this.cardDescription = document.getElementById('card-description');
        this.feedName = document.getElementById('feed-name');
        this.author = document.getElementById('author');
        this.cardBadge = document.getElementById('card-badge');
        this.cardContainer = document.getElementById('card-container');
        this.smartChip = document.getElementById('smart-chip');
        this.publishedTag = document.getElementById('published-tag');
        this.lengthTag = document.getElementById('length-tag');
        this.mediaTag = document.getElementById('media-tag');
        this.readBtn = document.getElementById('read-btn');

        this.nextCardPreview = document.getElementById('next-card-preview');
        this.nextTitle = document.getElementById('next-title');
        this.nextFeed = document.getElementById('next-feed');

        this.likeBtn = document.getElementById('like-btn');
        this.neutralBtn = document.getElementById('neutral-btn');
        this.dislikeBtn = document.getElementById('dislike-btn');
        this.actionsBar = document.querySelector('.actions');
        this.desktopMinimalControls = document.getElementById('desktop-minimal-controls');
        this.desktopLeftBtn = document.getElementById('desktop-left-btn');
        this.desktopRightBtn = document.getElementById('desktop-right-btn');
        this.desktopUpBtn = document.getElementById('desktop-up-btn');
        this.desktopDownBtn = document.getElementById('desktop-down-btn');
        this.gestureTips = document.querySelector('.gesture-tips');

        this.reviewedCount = document.getElementById('reviewed-count');
        this.remainingCount = document.getElementById('remaining-count');
        this.progressPercent = document.getElementById('progress-percent');
        this.progressFill = document.getElementById('progress-fill');
        this.dailyChip = document.getElementById('daily-chip');

        this.statsToggle = document.getElementById('stats-toggle');
        this.statsContent = document.getElementById('stats-content');

        this.loading = document.getElementById('loading');
        this.emptyState = document.getElementById('empty-state');
        this.noFeedsState = document.getElementById('no-feeds-state');
        this.toast = document.getElementById('status-toast');
        this.viewModeToggle = document.getElementById('view-mode-toggle');
        this.centerActionFeedback = document.getElementById('center-action-feedback');
        this.centerActionIcon = document.getElementById('center-action-icon');
        this.centerActionText = document.getElementById('center-action-text');
        this.minimalFullBtn = document.getElementById('minimal-full-btn');
        this.inAppBrowser = document.getElementById('inapp-browser');
        this.browserFrame = document.getElementById('browser-frame');
        this.browserLoading = document.getElementById('browser-loading');
        this.browserCloseBtn = document.getElementById('browser-close-btn');
        this.browserReloadBtn = document.getElementById('browser-reload-btn');
        this.browserDomainBtn = document.getElementById('browser-domain-btn');
        this.browserDomain = document.getElementById('browser-domain');

        this.settingsModal = document.getElementById('settings-modal');

        this.cardImg.addEventListener('error', () => {
            this.card.classList.add('no-image');
        });
    }

    attachEventListeners() {
        this.likeBtn.addEventListener('click', () => this.vote('like'));
        this.neutralBtn.addEventListener('click', () => this.vote('neutral'));
        this.dislikeBtn.addEventListener('click', () => this.vote('dislike'));

        if (this.desktopLeftBtn) {
            this.desktopLeftBtn.addEventListener('click', () => this.handleDesktopDirection('left'));
        }

        if (this.desktopRightBtn) {
            this.desktopRightBtn.addEventListener('click', () => this.handleDesktopDirection('right'));
        }

        if (this.desktopUpBtn) {
            this.desktopUpBtn.addEventListener('click', () => this.handleDesktopDirection('up'));
        }

        if (this.desktopDownBtn) {
            this.desktopDownBtn.addEventListener('click', () => this.handleDesktopDirection('down'));
        }

        this.readBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            this.openLink();
        });

        this.card.addEventListener('pointerdown', (event) => this.startDrag(event));
        window.addEventListener('pointermove', (event) => this.onDrag(event));
        window.addEventListener('pointerup', (event) => this.endDrag(event));
        window.addEventListener('pointercancel', (event) => this.endDrag(event));
        window.addEventListener('resize', () => this.refreshAdaptiveVisibility());

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && this.isBrowserOpen()) {
                this.closeInAppBrowser();
                return;
            }

            if (this.isBrowserOpen()) {
                return;
            }

            if (this.isSettingsOpen()) {
                return;
            }

            if (event.key === 'ArrowLeft' || event.key === '1') {
                this.vote('dislike');
            } else if (event.key === 'ArrowDown' || event.key.toLowerCase() === 'r') {
                this.nextPostAction();
            } else if (event.key === 'ArrowUp' || event.key === '2') {
                this.vote('neutral');
            } else if (event.key === 'ArrowRight' || event.key === '3') {
                this.vote('like');
            } else if (event.key === 'Enter') {
                this.openLink();
            }
        });

        document.addEventListener('touchmove', (event) => {
            if (this.isMobileViewport() && this.viewMode === 'minimal' && !this.isBrowserOpen() && !this.isSettingsOpen()) {
                event.preventDefault();
            }
        }, { passive: false });

        this.statsToggle.addEventListener('click', () => {
            this.statsContent.classList.toggle('open');
        });

        const openSettingsBtn = document.getElementById('open-settings-btn');
        if (openSettingsBtn) {
            openSettingsBtn.addEventListener('click', () => {
                const settingsBtn = document.getElementById('settings-btn');
                if (settingsBtn) {
                    settingsBtn.click();
                } else if (this.settingsModal) {
                    this.settingsModal.classList.add('active');
                }
            });
        }

        if (this.viewModeToggle) {
            this.viewModeToggle.addEventListener('click', () => this.toggleViewMode());
        }

        if (this.minimalFullBtn) {
            this.minimalFullBtn.addEventListener('click', () => this.toggleViewMode());
        }

        if (this.browserCloseBtn) {
            this.browserCloseBtn.addEventListener('click', () => this.closeInAppBrowser());
        }

        if (this.browserReloadBtn) {
            this.browserReloadBtn.addEventListener('click', () => this.reloadInAppBrowser());
        }

        if (this.browserDomainBtn) {
            this.browserDomainBtn.addEventListener('click', () => this.openBrowserExternal());
        }

        if (this.browserFrame) {
            this.browserFrame.addEventListener('load', () => this.onBrowserFrameLoaded());
        }
    }

    isSettingsOpen() {
        return Boolean(this.settingsModal && this.settingsModal.classList.contains('active'));
    }

    isBrowserOpen() {
        return Boolean(this.inAppBrowser && this.inAppBrowser.classList.contains('open'));
    }

    isMobileViewport() {
        return window.matchMedia('(max-width: 767px)').matches;
    }

    initViewMode() {
        let storedMode = null;
        try {
            storedMode = localStorage.getItem(this.viewModeKey);
        } catch (error) {
            storedMode = null;
        }

        if (storedMode === 'minimal' || storedMode === 'full') {
            this.viewMode = storedMode;
        } else {
            this.viewMode = this.isMobileViewport() ? 'minimal' : 'full';
        }

        this.setViewMode(this.viewMode, false);
    }

    setViewMode(mode, persist = true) {
        this.viewMode = mode === 'full' ? 'full' : 'minimal';
        document.body.classList.toggle('view-minimal', this.viewMode === 'minimal');
        document.body.classList.toggle('view-full', this.viewMode === 'full');
        this.syncModeToggle(this.viewModeToggle);
        this.syncModeToggle(this.minimalFullBtn);

        if (persist) {
            try {
                localStorage.setItem(this.viewModeKey, this.viewMode);
            } catch (error) {
                // localStorage might be disabled.
            }
        }

        this.refreshAdaptiveVisibility();
    }

    toggleViewMode() {
        const nextMode = this.viewMode === 'minimal' ? 'full' : 'minimal';
        this.setViewMode(nextMode);
    }

    syncModeToggle(toggleEl) {
        if (!toggleEl) {
            return;
        }

        const isMinimal = this.viewMode === 'minimal';
        toggleEl.classList.toggle('is-minimal', isMinimal);
        toggleEl.classList.toggle('is-full', !isMinimal);
        toggleEl.setAttribute('aria-checked', isMinimal ? 'true' : 'false');
        toggleEl.setAttribute('aria-label', isMinimal ? '切换到完整模式' : '切换到极简模式');
    }

    refreshAdaptiveVisibility(forceShow = false) {
        const deckHidden = this.cardContainer && this.cardContainer.style.display === 'none';
        const hideForMinimal = this.viewMode === 'minimal';
        const showDesktopMinimalControls = hideForMinimal && !this.isMobileViewport() && !deckHidden;

        if (this.desktopMinimalControls) {
            this.desktopMinimalControls.style.display = showDesktopMinimalControls ? 'grid' : 'none';
        }

        if (deckHidden && !forceShow) {
            return;
        }

        if (this.actionsBar) {
            this.actionsBar.style.display = hideForMinimal ? 'none' : 'grid';
        }

        if (this.gestureTips) {
            this.gestureTips.style.display = hideForMinimal ? 'none' : 'flex';
        }
    }

    handleDesktopDirection(direction) {
        if (this.isBrowserOpen() || this.isSettingsOpen() || this.isVoting) {
            return;
        }

        if (direction === 'left') {
            this.vote('dislike');
            return;
        }

        if (direction === 'right') {
            this.vote('like');
            return;
        }

        if (direction === 'up') {
            this.vote('neutral');
            return;
        }

        if (direction === 'down') {
            this.nextPostAction();
        }
    }

    async displayNextPost() {
        const post = this.preloadQueue.getNext();

        if (post) {
            this.showDeck();
            this.currentPost = post;
            this.startTime = Date.now();
            this.renderPost(post);
            this.updateNextPreview();
            this.showLoading(false);
            this.enhanceWithOpenGraph(post);
            return;
        }

        await this.loadNextPostFallback();
    }

    async loadNextPostFallback() {
        this.showLoading(true);

        try {
            const excludeIds = [...this.preloadQueue.getQueuedIds()];
            if (this.currentPost?.id) {
                excludeIds.push(this.currentPost.id);
            }

            const response = await fetch(`/api/posts/next?exclude=${excludeIds.join(',')}`);

            if (response.status === 404) {
                await this.showEmptyState();
                return;
            }

            if (!response.ok) {
                throw new Error(`Unexpected status: ${response.status}`);
            }

            const post = await response.json();
            this.showDeck();
            this.currentPost = post;
            this.startTime = Date.now();
            this.renderPost(post);
            this.showLoading(false);

            this.preloadQueue.fetchBatch([post.id]);
            this.updateNextPreview();
            this.enhanceWithOpenGraph(post);
        } catch (error) {
            console.error('Failed to load next post:', error);
            this.showLoading(false);
            this.showToast('加载失败，请稍后重试');
        }
    }

    async loadNextPost() {
        if (this.currentPost && this.startTime) {
            const secondsSpent = Math.floor((Date.now() - this.startTime) / 1000);
            await this.recordTime(this.currentPost.id, secondsSpent);
        }

        await this.displayNextPost();
    }

    renderPost(post) {
        this.card.style.transform = '';
        this.card.className = 'card';
        this.cardBadge.className = 'card-badge';
        this.clearDragIntent();

        this.cardTitle.textContent = post.title || 'Untitled';
        this.cardDescription.textContent = post.description || 'No description available.';
        this.feedName.textContent = post.feed_name || 'Unknown source';
        this.author.textContent = post.author || '匿名作者';

        this.publishedTag.textContent = this.getPublishedLabel(post.published_at);
        this.lengthTag.textContent = this.getReadingLabel(post);
        this.mediaTag.textContent = this.getMediaLabel(post);
        this.smartChip.textContent = this.getSmartReason(post);

        this.setCardImage(post);
    }

    setCardImage(post) {
        const imageUrl = post.image_url;

        if (imageUrl) {
            this.cardImg.src = imageUrl;
            this.card.classList.remove('no-image');
            return;
        }

        const colorA = this.stringToColor(post.feed_name || 'feed');
        const colorB = this.stringToColor(post.title || 'title');
        this.cardImg.removeAttribute('src');
        this.card.querySelector('.card-image-fallback').style.background = `linear-gradient(150deg, ${colorA} 0%, ${colorB} 100%)`;
        this.card.classList.add('no-image');
    }

    getPublishedLabel(rawDate) {
        if (!rawDate) {
            return '发布时间未知';
        }

        const date = new Date(rawDate);
        if (Number.isNaN(date.getTime())) {
            return '发布时间未知';
        }

        const diffMs = Date.now() - date.getTime();
        const minute = 60 * 1000;
        const hour = 60 * minute;
        const day = 24 * hour;

        if (diffMs < hour) {
            const minutes = Math.max(1, Math.round(diffMs / minute));
            return `${minutes} 分钟前`;
        }

        if (diffMs < day) {
            const hours = Math.max(1, Math.round(diffMs / hour));
            return `${hours} 小时前`;
        }

        if (diffMs < day * 7) {
            const days = Math.max(1, Math.round(diffMs / day));
            return `${days} 天前`;
        }

        return `${date.getMonth() + 1}月${date.getDate()}日`;
    }

    getReadingLabel(post) {
        const text = `${post.title || ''} ${post.description || ''}`.trim();
        const chars = text.replace(/\s+/g, '').length;

        if (chars > 420) {
            return '深度长读';
        }

        if (chars > 190) {
            return '标准阅读';
        }

        return '轻量快读';
    }

    getMediaLabel(post) {
        if (post.image_url || post.has_media) {
            return '图文内容';
        }

        return '纯文本';
    }

    getSmartReason(post) {
        const text = `${post.title || ''} ${post.description || ''}`.toLowerCase();
        const keywordMap = [
            { key: /ai|gpt|llm|openai|machine learning/, label: 'AI 相关内容热度高' },
            { key: /security|privacy|漏洞|安全/, label: '安全主题，值得关注' },
            { key: /ios|android|mobile|app|产品/, label: '移动产品相关文章' },
            { key: /design|ux|ui|体验/, label: '体验设计方向内容' }
        ];

        for (const item of keywordMap) {
            if (item.key.test(text)) {
                return item.label;
            }
        }

        if (post.published_at) {
            const date = new Date(post.published_at);
            if (!Number.isNaN(date.getTime()) && Date.now() - date.getTime() < 36 * 60 * 60 * 1000) {
                return '新鲜发布，优先推荐';
            }
        }

        if (post.image_url || post.has_media) {
            return '含封面图，适合快速浏览';
        }

        const fallbacks = [
            '根据你最近的偏好挑选',
            '来自你的订阅源精选',
            '智能排序命中你的兴趣'
        ];

        return fallbacks[post.id % fallbacks.length];
    }

    async vote(voteType) {
        if (!this.currentPost || this.isVoting) {
            return;
        }

        this.isVoting = true;
        this.showVoteHint(voteType);
        setTimeout(() => {
            if (voteType === 'like') {
                this.card.classList.add('swipe-right');
            } else if (voteType === 'dislike') {
                this.card.classList.add('swipe-left');
            } else {
                this.card.classList.add('swipe-down');
            }
        }, 95);

        try {
            const response = await fetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    entry_id: this.currentPost.id,
                    vote: voteType
                })
            });

            if (!response.ok) {
                throw new Error(`Vote failed with status ${response.status}`);
            }

            this.loadStats();

            setTimeout(async () => {
                this.isVoting = false;
                this.hideCenterAction();
                await this.loadNextPost();
            }, 340);
        } catch (error) {
            console.error('Vote failed:', error);
            this.isVoting = false;
            this.card.classList.remove('swipe-left', 'swipe-right', 'swipe-down');
            this.resetCardPosition();
            this.hideCenterAction();
            this.showToast('提交失败，请重试');
        }
    }

    getVoteMeta(voteType) {
        const map = {
            like: { text: '收藏', icon: '❤' },
            neutral: { text: '稍后阅读', icon: '⏺' },
            dislike: { text: '跳过', icon: '✕' },
            next: { text: '下一个', icon: '↧' }
        };
        return map[voteType] || { text: voteType, icon: '•' };
    }

    showCenterAction(voteType, preview = false) {
        if (!this.centerActionFeedback || !this.centerActionText || !this.centerActionIcon) {
            return;
        }

        const meta = this.getVoteMeta(voteType);
        this.centerActionText.textContent = meta.text;
        this.centerActionIcon.textContent = meta.icon;
        this.centerActionFeedback.className = `center-action-feedback show ${voteType} ${preview ? 'preview' : 'commit'}`;

        if (preview) {
            return;
        }
    }

    hideCenterAction() {
        if (!this.centerActionFeedback) {
            return;
        }
        this.centerActionFeedback.className = 'center-action-feedback';
    }

    showVoteHint(voteType) {
        const meta = this.getVoteMeta(voteType);
        const badgeText = voteType === 'neutral' ? '稍后' : (voteType === 'next' ? '下一个' : meta.text);

        this.cardBadge.textContent = badgeText;
        this.cardBadge.className = `card-badge show ${voteType}`;
        this.showCenterAction(voteType, false);
    }

    nextPostAction() {
        if (!this.currentPost || this.isVoting) {
            return;
        }

        this.isVoting = true;
        this.showVoteHint('next');
        setTimeout(() => {
            this.card.classList.add('swipe-down');
        }, 95);

        setTimeout(async () => {
            this.isVoting = false;
            this.hideCenterAction();
            await this.loadNextPost();
        }, 330);
    }

    openLink() {
        if (!this.currentPost || this.isSettingsOpen() || this.isBrowserOpen()) {
            return;
        }

        const now = Date.now();
        if (now < this.linkOpenLockedUntil) {
            return;
        }
        this.linkOpenLockedUntil = now + 700;

        const url = this.currentPost.permalink || this.currentPost.link;
        if (!url) {
            this.showToast('该文章没有可打开的链接');
            return;
        }

        this.recordLinkOpen(this.currentPost.id);

        if (this.shouldUseInAppBrowser()) {
            this.openInAppBrowser(url);
            return;
        }

        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        anchor.style.display = 'none';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
    }

    shouldUseInAppBrowser() {
        return this.isMobileViewport();
    }

    openInAppBrowser(url) {
        if (!this.inAppBrowser || !this.browserFrame) {
            window.location.href = url;
            return;
        }

        this.browserUrl = url;
        if (this.browserDomain) {
            this.browserDomain.textContent = this.getDomainLabel(url);
        }
        if (this.browserLoading) {
            this.browserLoading.classList.add('show');
        }

        this.inAppBrowser.classList.add('open');
        this.inAppBrowser.setAttribute('aria-hidden', 'false');
        document.body.classList.add('browser-open');
        this.browserFrame.src = url;
    }

    closeInAppBrowser() {
        if (!this.inAppBrowser) {
            return;
        }

        this.inAppBrowser.classList.remove('open');
        this.inAppBrowser.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('browser-open');
        if (this.browserLoading) {
            this.browserLoading.classList.remove('show');
        }

        setTimeout(() => {
            if (this.browserFrame) {
                this.browserFrame.src = 'about:blank';
            }
        }, 180);
    }

    reloadInAppBrowser() {
        if (!this.browserFrame || !this.browserUrl) {
            return;
        }

        if (this.browserLoading) {
            this.browserLoading.classList.add('show');
        }
        this.browserFrame.src = this.browserUrl;
    }

    openBrowserExternal() {
        if (!this.browserUrl) {
            return;
        }

        window.open(this.browserUrl, '_blank', 'noopener,noreferrer');
    }

    onBrowserFrameLoaded() {
        if (this.browserLoading) {
            this.browserLoading.classList.remove('show');
        }
    }

    getDomainLabel(url) {
        try {
            return new URL(url).hostname.replace(/^www\./, '');
        } catch (error) {
            return 'article';
        }
    }

    recordLinkOpen(entryId) {
        if (!entryId) {
            return;
        }

        const payload = JSON.stringify({ entry_id: entryId });
        let sent = false;

        try {
            if (navigator.sendBeacon) {
                const blob = new Blob([payload], { type: 'application/json' });
                sent = navigator.sendBeacon('/api/open', blob);
            }
        } catch (error) {
            sent = false;
        }

        if (sent) {
            return;
        }

        fetch('/api/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload,
            keepalive: true
        }).catch((error) => {
            console.error('Link open tracking failed:', error);
        });
    }

    async recordTime(entryId, seconds) {
        if (!entryId || seconds < 1) {
            return;
        }

        try {
            await fetch('/api/time', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    entry_id: entryId,
                    seconds
                })
            });
        } catch (error) {
            console.error('Time recording failed:', error);
        }
    }

    async loadStats() {
        try {
            const response = await fetch('/api/stats');
            if (!response.ok) {
                throw new Error(`Stats request failed: ${response.status}`);
            }

            const stats = await response.json();

            this.reviewedCount.textContent = stats.posts_reviewed ?? 0;
            this.remainingCount.textContent = stats.posts_remaining ?? 0;
            this.progressPercent.textContent = `${stats.completion_percent ?? 0}%`;

            const progress = Math.max(0, Math.min(100, Number(stats.completion_percent || 0)));
            this.progressFill.style.width = `${progress}%`;

            document.getElementById('total-likes').textContent = stats.likes ?? 0;
            document.getElementById('total-neutral').textContent = stats.neutral ?? 0;
            document.getElementById('total-dislikes').textContent = stats.dislikes ?? 0;
            document.getElementById('links-opened').textContent = stats.links_opened ?? 0;
            document.getElementById('time-spent').textContent = `${stats.total_time_minutes ?? 0}m`;
            document.getElementById('today-votes').textContent = stats.today_votes ?? 0;

            if (stats.ml_model?.enabled) {
                this.dailyChip.textContent = 'AI 推荐开启';
            } else {
                this.dailyChip.textContent = '随机模式';
            }
        } catch (error) {
            console.error('Loading stats failed:', error);
        }
    }

    updateNextPreview() {
        const next = this.preloadQueue.peek();

        if (!next) {
            this.nextCardPreview.classList.add('hidden');
            this.nextTitle.textContent = '正在挑选下一篇…';
            this.nextFeed.textContent = 'Smart picker';
            return;
        }

        this.nextCardPreview.classList.remove('hidden');
        this.nextTitle.textContent = this.truncate(next.title || 'Untitled', 74);
        this.nextFeed.textContent = next.feed_name || 'Unknown source';
    }

    async enhanceWithOpenGraph(post) {
        if (!post?.id) {
            return;
        }

        if (this.ogCache.has(post.id)) {
            this.applyOpenGraph(this.ogCache.get(post.id), post);
            return;
        }

        try {
            const response = await fetch(`/api/og/${post.id}`);
            if (!response.ok) {
                return;
            }

            const data = await response.json();
            this.ogCache.set(post.id, data);

            if (this.currentPost?.id === post.id) {
                this.applyOpenGraph(data, post);
            }
        } catch (error) {
            console.error('Open Graph fetch failed:', error);
        }
    }

    applyOpenGraph(data, post) {
        if (!data || data.error || this.currentPost?.id !== post.id) {
            return;
        }

        if (!post.image_url && data.image) {
            this.cardImg.src = data.image;
            this.card.classList.remove('no-image');
        }

        if (data.site_name && !this.feedName.textContent.includes(data.site_name)) {
            this.feedName.textContent = `${post.feed_name} · ${data.site_name}`;
        }

        if (data.description && this.cardDescription.textContent.length < 80) {
            this.cardDescription.textContent = this.truncate(data.description, 220);
        }
    }

    startDrag(event) {
        if (this.isVoting || !this.currentPost || this.isSettingsOpen() || this.isBrowserOpen()) {
            return;
        }

        if (event.target.closest('button, a, input, textarea')) {
            return;
        }

        if (event.pointerType === 'mouse' && event.button !== 0) {
            return;
        }

        this.isDragging = true;
        this.hasMoved = false;
        this.touchStartTime = Date.now();
        this.activePointerId = event.pointerId;
        this.dragStartX = event.clientX;
        this.dragStartY = event.clientY;
        this.lastDeltaX = 0;
        this.lastDeltaY = 0;

        if (this.card.setPointerCapture) {
            this.card.setPointerCapture(event.pointerId);
        }

        this.card.classList.add('dragging');
        this.hideCenterAction();
    }

    onDrag(event) {
        if (!this.isDragging || event.pointerId !== this.activePointerId) {
            return;
        }

        const deltaX = event.clientX - this.dragStartX;
        const deltaY = event.clientY - this.dragStartY;

        this.lastDeltaX = deltaX;
        this.lastDeltaY = deltaY;

        if (Math.abs(deltaX) > 7 || Math.abs(deltaY) > 7) {
            this.hasMoved = true;
        }

        const rotate = deltaX / 22;
        this.card.style.transform = `translate(${deltaX}px, ${deltaY}px) rotate(${rotate}deg)`;

        this.updateDragIntent(deltaX, deltaY);
    }

    endDrag(event) {
        if (!this.isDragging || event.pointerId !== this.activePointerId) {
            return;
        }

        this.isDragging = false;
        this.card.classList.remove('dragging');

        if (this.card.releasePointerCapture) {
            this.card.releasePointerCapture(event.pointerId);
        }

        const touchDuration = Date.now() - this.touchStartTime;
        const deltaX = this.lastDeltaX;
        const deltaY = this.lastDeltaY;

        if (!this.hasMoved && touchDuration < 260) {
            this.resetCardPosition();
            this.openLink();
            return;
        }

        if (deltaX > this.getSwipeThresholdX()) {
            this.vote('like');
            return;
        }

        if (deltaX < -this.getSwipeThresholdX()) {
            this.vote('dislike');
            return;
        }

        if (deltaY > this.getSwipeThresholdY()) {
            this.nextPostAction();
            return;
        }

        if (deltaY < -this.getSwipeThresholdY()) {
            this.vote('neutral');
            return;
        }

        this.resetCardPosition();
    }

    getSwipeThresholdX() {
        return Math.max(95, Math.min(140, window.innerWidth * 0.25));
    }

    getSwipeThresholdY() {
        return Math.max(100, Math.min(160, window.innerHeight * 0.18));
    }

    updateDragIntent(deltaX, deltaY) {
        this.clearDragIntent();

        if (Math.abs(deltaX) > 42) {
            if (deltaX > 0) {
                this.cardBadge.textContent = '收藏';
                this.cardBadge.className = 'card-badge show like';
                this.likeBtn.classList.add('preview-like');
                this.showCenterAction('like', true);
            } else {
                this.cardBadge.textContent = '跳过';
                this.cardBadge.className = 'card-badge show dislike';
                this.dislikeBtn.classList.add('preview-dislike');
                this.showCenterAction('dislike', true);
            }
            return;
        }

        if (deltaY > 46) {
            this.cardBadge.textContent = '下一个';
            this.cardBadge.className = 'card-badge show next';
            this.showCenterAction('next', true);
            return;
        }

        if (deltaY < -46) {
            this.cardBadge.textContent = '稍后';
            this.cardBadge.className = 'card-badge show neutral';
            this.neutralBtn.classList.add('preview-neutral');
            this.showCenterAction('neutral', true);
            return;
        }

        this.cardBadge.className = 'card-badge';
        this.hideCenterAction();
    }

    clearDragIntent() {
        this.likeBtn.classList.remove('preview-like');
        this.neutralBtn.classList.remove('preview-neutral');
        this.dislikeBtn.classList.remove('preview-dislike');
    }

    resetCardPosition() {
        this.card.style.transform = '';
        this.cardBadge.className = 'card-badge';
        this.clearDragIntent();
        this.hideCenterAction();
    }

    showLoading(visible) {
        this.loading.classList.toggle('show', visible);
    }

    async showEmptyState() {
        this.showLoading(false);
        this.cardContainer.style.display = 'none';
        this.actionsBar.style.display = 'none';
        this.gestureTips.style.display = 'none';
        if (this.desktopMinimalControls) {
            this.desktopMinimalControls.style.display = 'none';
        }
        this.hideCenterAction();

        try {
            const response = await fetch('/api/stats');
            const stats = await response.json();

            if ((stats.total_posts ?? 0) === 0) {
                this.noFeedsState.style.display = 'block';
                this.emptyState.style.display = 'none';
            } else {
                this.emptyState.style.display = 'block';
                this.noFeedsState.style.display = 'none';
            }
        } catch (error) {
            this.noFeedsState.style.display = 'block';
            this.emptyState.style.display = 'none';
        }
    }

    showDeck() {
        this.cardContainer.style.display = 'flex';
        this.refreshAdaptiveVisibility(true);
        this.emptyState.style.display = 'none';
        this.noFeedsState.style.display = 'none';
    }

    showToast(message) {
        if (!this.toast) {
            return;
        }

        this.toast.textContent = message;
        this.toast.classList.add('show');

        if (this.toastTimer) {
            clearTimeout(this.toastTimer);
        }

        this.toastTimer = setTimeout(() => {
            this.toast.classList.remove('show');
        }, 2100);
    }

    truncate(text, maxLength = 140) {
        if (!text || text.length <= maxLength) {
            return text || '';
        }

        return `${text.slice(0, maxLength - 1).trimEnd()}…`;
    }

    stringToColor(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i += 1) {
            hash = str.charCodeAt(i) + ((hash << 5) - hash);
        }

        const hue = ((hash % 360) + 360) % 360;
        return `hsl(${hue}, 58%, 68%)`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new RSSSwipr();
});
