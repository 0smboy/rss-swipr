// RSS Swipr - Main App Logic

/**
 * PreloadQueue - Manages background preloading of posts for instant display
 */
class PreloadQueue {
    constructor(batchSize = 3, minQueueSize = 1) {
        this.queue = [];
        this.batchSize = batchSize;
        this.minQueueSize = minQueueSize;
        this.isFetching = false;
        this.onQueueUpdated = null;  // Callback when queue changes
    }

    /**
     * Get IDs of posts currently in queue (to exclude from next fetch)
     */
    getQueuedIds() {
        return this.queue.map(post => post.id);
    }

    /**
     * Fetch a batch of posts from the server
     * @param {number[]} additionalExcludeIds - Extra IDs to exclude (e.g., current post)
     */
    async fetchBatch(additionalExcludeIds = []) {
        if (this.isFetching) return;

        this.isFetching = true;
        try {
            const excludeIds = [...this.getQueuedIds(), ...additionalExcludeIds];
            const url = `/api/posts/batch?count=${this.batchSize}&exclude=${excludeIds.join(',')}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                console.error('Batch fetch failed:', response.status);
                return;
            }
            
            const data = await response.json();
            if (data.posts && data.posts.length > 0) {
                this.queue.push(...data.posts);
                console.log(`Preloaded ${data.posts.length} posts, queue size: ${this.queue.length}`);
            }
        } catch (error) {
            console.error('Error fetching batch:', error);
        } finally {
            this.isFetching = false;
        }
    }

    /**
     * Get next post from queue. Returns null if empty.
     */
    getNext() {
        if (this.queue.length === 0) return null;

        const post = this.queue.shift();

        // Trigger background fetch if queue is running low
        // Exclude the post we're about to display to prevent duplicates
        if (this.queue.length < this.minQueueSize && !this.isFetching) {
            this.fetchBatch([post.id]);
        }

        return post;
    }

    /**
     * Check if queue has posts available
     */
    hasNext() {
        return this.queue.length > 0;
    }

    /**
     * Get current queue size
     */
    size() {
        return this.queue.length;
    }

    /**
     * Remove a specific post from queue (if voted on while still in queue)
     */
    removeById(id) {
        this.queue = this.queue.filter(post => post.id !== id);
    }
}


class RSSSwipr {
    constructor() {
        this.currentPost = null;
        this.startTime = null;
        this.dragStartX = 0;
        this.dragStartY = 0;
        this.isDragging = false;
        
        // Initialize preload queue (fetch 3 posts, refill when < 1 remain)
        this.preloadQueue = new PreloadQueue(3, 1);
        
        this.init();
    }
    
    async init() {
        this.bindElements();
        this.attachEventListeners();
        this.loadStats();
        
        // Initial load: fetch batch then display first post
        this.showLoading(true);
        await this.preloadQueue.fetchBatch();
        this.displayNextPost();
    }
    
    bindElements() {
        // Card elements
        this.card = document.getElementById('card');
        this.cardImg = document.getElementById('card-img');
        this.cardTitle = document.getElementById('card-title');
        this.cardDescription = document.getElementById('card-description');
        this.feedName = document.getElementById('feed-name');
        this.author = document.getElementById('author');
        this.cardBadge = document.getElementById('card-badge');
        this.cardContainer = document.getElementById('card-container');

        // Action buttons
        this.likeBtn = document.getElementById('like-btn');
        this.neutralBtn = document.getElementById('neutral-btn');
        this.dislikeBtn = document.getElementById('dislike-btn');

        // Stats elements
        this.reviewedCount = document.getElementById('reviewed-count');
        this.remainingCount = document.getElementById('remaining-count');
        this.progressPercent = document.getElementById('progress-percent');
        this.statsToggle = document.getElementById('stats-toggle');
        this.statsContent = document.getElementById('stats-content');

        // UI states
        this.loading = document.getElementById('loading');
        this.emptyState = document.getElementById('empty-state');
        this.noFeedsState = document.getElementById('no-feeds-state');
    }
    
    attachEventListeners() {
        // Button clicks
        this.likeBtn.addEventListener('click', () => this.vote('like'));
        this.neutralBtn.addEventListener('click', () => this.vote('neutral'));
        this.dislikeBtn.addEventListener('click', () => this.vote('dislike'));
        
        // Card click to open link
        this.card.addEventListener('click', (e) => {
            // Don't trigger if clicking action buttons
            if (!e.target.closest('.actions')) {
                this.openLink();
            }
        });
        
        // Keyboard controls
        document.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft' || e.key === '1') {
                this.vote('dislike');
            } else if (e.key === 'ArrowDown' || e.key === '2') {
                this.vote('neutral');
            } else if (e.key === 'ArrowRight' || e.key === '3') {
                this.vote('like');
            }
        });
        
        // Mouse drag
        this.card.addEventListener('mousedown', (e) => this.startDrag(e));
        document.addEventListener('mousemove', (e) => this.onDrag(e));
        document.addEventListener('mouseup', () => this.endDrag());
        
        // Touch support
        this.card.addEventListener('touchstart', (e) => this.startDrag(e.touches[0]));
        document.addEventListener('touchmove', (e) => this.onDrag(e.touches[0]));
        document.addEventListener('touchend', () => this.endDrag());
        
        // Stats toggle
        this.statsToggle.addEventListener('click', () => {
            this.statsContent.classList.toggle('open');
        });

        // Open settings button (shown when no feeds)
        const openSettingsBtn = document.getElementById('open-settings-btn');
        if (openSettingsBtn) {
            openSettingsBtn.addEventListener('click', () => {
                document.getElementById('settings-modal').classList.add('open');
            });
        }
    }
    
    /**
     * Display next post from preload queue (instant) or fetch if queue empty
     */
    displayNextPost() {
        // Try to get from preload queue first (instant)
        const post = this.preloadQueue.getNext();
        
        if (post) {
            this.currentPost = post;
            this.startTime = Date.now();
            this.renderPost(post);
            this.showLoading(false);
            console.log(`Displayed post ${post.id}, queue remaining: ${this.preloadQueue.size()}`);
        } else {
            // Queue empty - fetch and wait (fallback)
            this.loadNextPostFallback();
        }
    }
    
    /**
     * Fallback: fetch single post when queue is empty
     */
    async loadNextPostFallback() {
        this.showLoading(true);

        try {
            // Build exclude list from queue + current post to prevent duplicates
            const excludeIds = [...this.preloadQueue.getQueuedIds()];
            if (this.currentPost) excludeIds.push(this.currentPost.id);
            const url = `/api/posts/next?exclude=${excludeIds.join(',')}`;

            const response = await fetch(url);

            if (response.status === 404) {
                this.showEmptyState();
                return;
            }

            const post = await response.json();
            this.currentPost = post;
            this.startTime = Date.now();
            this.renderPost(post);
            this.showLoading(false);

            // Trigger background refill, excluding the post we just fetched
            this.preloadQueue.fetchBatch([post.id]);

        } catch (error) {
            console.error('Error loading post:', error);
            this.showLoading(false);
        }
    }
    
    async loadNextPost() {
        // Record time spent on previous post
        if (this.currentPost && this.startTime) {
            const timeSpent = Math.floor((Date.now() - this.startTime) / 1000);
            await this.recordTime(this.currentPost.id, timeSpent);
        }
        
        // Use preload queue for instant display
        this.displayNextPost();
    }
    
    renderPost(post) {
        this.cardTitle.textContent = post.title;
        this.cardDescription.textContent = post.description || 'No description available.';
        this.feedName.textContent = post.feed_name;
        this.author.textContent = post.author || '';
        
        // Set image (use placeholder if no image)
        if (post.image_url) {
            this.cardImg.src = post.image_url;
            this.cardImg.style.display = 'block';
        } else {
            // Generate a gradient background based on feed name
            const color1 = this.stringToColor(post.feed_name);
            const color2 = this.stringToColor(post.title);
            this.cardImg.style.display = 'none';
            this.cardImg.parentElement.style.background = `linear-gradient(135deg, ${color1} 0%, ${color2} 100%)`;
        }
        
        // Reset card position
        this.card.style.transform = '';
        this.card.className = 'card';
        this.cardBadge.className = 'card-badge';
    }
    
    async vote(voteType) {
        if (!this.currentPost) return;
        
        // Show badge animation
        this.cardBadge.textContent = voteType.toUpperCase();
        this.cardBadge.classList.add('show', voteType);
        
        // Animate card away
        if (voteType === 'like') {
            this.card.classList.add('swipe-right');
        } else if (voteType === 'dislike') {
            this.card.classList.add('swipe-left');
        } else {
            this.card.classList.add('swipe-down');
        }
        
        // Record vote
        try {
            await fetch('/api/vote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    entry_id: this.currentPost.id,
                    vote: voteType
                })
            });
            
            // Update stats
            await this.loadStats();
            
            // Load next post after animation
            setTimeout(() => {
                this.loadNextPost();
            }, 300);
            
        } catch (error) {
            console.error('Error recording vote:', error);
        }
    }
    
    async openLink() {
        if (!this.currentPost) return;
        
        // Record link open
        try {
            await fetch('/api/open', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    entry_id: this.currentPost.id
                })
            });
            
            // Open link in new tab
            const url = this.currentPost.permalink || this.currentPost.link;
            if (url) {
                window.open(url, '_blank');
            }
            
        } catch (error) {
            console.error('Error recording link open:', error);
        }
    }
    
    async recordTime(entryId, seconds) {
        if (seconds < 1) return; // Don't record trivial times
        
        try {
            await fetch('/api/time', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    entry_id: entryId,
                    seconds: seconds
                })
            });
        } catch (error) {
            console.error('Error recording time:', error);
        }
    }
    
    async loadStats() {
        try {
            const response = await fetch('/api/stats');
            const stats = await response.json();
            
            // Update header stats
            this.reviewedCount.textContent = stats.posts_reviewed;
            this.remainingCount.textContent = stats.posts_remaining;
            this.progressPercent.textContent = `${stats.completion_percent}%`;
            
            // Update detailed stats
            document.getElementById('total-likes').textContent = stats.likes;
            document.getElementById('total-neutral').textContent = stats.neutral;
            document.getElementById('total-dislikes').textContent = stats.dislikes;
            document.getElementById('links-opened').textContent = stats.links_opened;
            document.getElementById('time-spent').textContent = `${stats.total_time_minutes}m`;
            document.getElementById('today-votes').textContent = stats.today_votes;
            
        } catch (error) {
            console.error('Error loading stats:', error);
        }
    }
    
    startDrag(e) {
        this.isDragging = true;
        this.dragStartX = e.clientX || e.pageX;
        this.dragStartY = e.clientY || e.pageY;
        this.card.classList.add('dragging');
    }
    
    onDrag(e) {
        if (!this.isDragging) return;
        
        const currentX = e.clientX || e.pageX;
        const currentY = e.clientY || e.pageY;
        const deltaX = currentX - this.dragStartX;
        const deltaY = currentY - this.dragStartY;
        
        // Apply transform
        const rotation = deltaX * 0.1; // Slight rotation
        this.card.style.transform = `translate(${deltaX}px, ${deltaY}px) rotate(${rotation}deg)`;
        
        // Show badge based on drag direction
        if (Math.abs(deltaX) > 50) {
            if (deltaX > 0) {
                this.cardBadge.textContent = 'LIKE';
                this.cardBadge.className = 'card-badge show like';
            } else {
                this.cardBadge.textContent = 'DISLIKE';
                this.cardBadge.className = 'card-badge show dislike';
            }
        } else if (deltaY > 50) {
            this.cardBadge.textContent = 'NEUTRAL';
            this.cardBadge.className = 'card-badge show neutral';
        } else {
            this.cardBadge.className = 'card-badge';
        }
    }
    
    endDrag() {
        if (!this.isDragging) return;
        
        this.isDragging = false;
        this.card.classList.remove('dragging');
        
        const transform = this.card.style.transform;
        const match = transform.match(/translate\((-?\d+)px, (-?\d+)px\)/);
        
        if (match) {
            const deltaX = parseInt(match[1]);
            const deltaY = parseInt(match[2]);
            
            // Determine if drag was significant enough
            if (deltaX > 100) {
                this.vote('like');
                return;
            } else if (deltaX < -100) {
                this.vote('dislike');
                return;
            } else if (deltaY > 100) {
                this.vote('neutral');
                return;
            }
        }
        
        // Reset position
        this.card.style.transform = '';
        this.cardBadge.className = 'card-badge';
    }
    
    showLoading(show) {
        if (show) {
            this.loading.classList.add('show');
        } else {
            this.loading.classList.remove('show');
        }
    }
    
    async showEmptyState() {
        this.showLoading(false);
        this.cardContainer.style.display = 'none';
        document.querySelector('.actions').style.display = 'none';

        // Check if there are any posts at all to determine which state to show
        try {
            const response = await fetch('/api/stats');
            const stats = await response.json();

            if (stats.total_posts === 0) {
                // No posts at all - show "add feeds" state
                this.noFeedsState.style.display = 'block';
                this.emptyState.style.display = 'none';
            } else {
                // All posts reviewed - show "all done" state
                this.emptyState.style.display = 'block';
                this.noFeedsState.style.display = 'none';
            }
        } catch (error) {
            // Fallback to no-feeds state
            this.noFeedsState.style.display = 'block';
        }
    }
    
    stringToColor(str) {
        // Generate a color from string
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            hash = str.charCodeAt(i) + ((hash << 5) - hash);
        }
        const hue = hash % 360;
        return `hsl(${hue}, 70%, 60%)`;
    }
}

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new RSSSwipr();
});
