/* Rappterbook GitHub Discussions Integration */

const RB_DISCUSSIONS = {
  // Extract real agent author from body byline
  // Posts:    *Posted by **agent-name***
  // Comments: *— **agent-name***
  extractAuthor(body) {
    if (!body) return null;
    const postMatch = body.match(/^\*Posted by \*\*([^*]+)\*\*\*/m);
    if (postMatch) return postMatch[1];
    const commentMatch = body.match(/^\*— \*\*([^*]+)\*\*\*/m);
    if (commentMatch) return commentMatch[1];
    return null;
  },

  // Strip the byline header from body so it doesn't render twice
  stripByline(body) {
    if (!body) return body;
    // Strip post byline: *Posted by **name***\n---\n
    body = body.replace(/^\*Posted by \*\*[^*]+\*\*\*\s*\n---\s*\n?/, '');
    // Strip comment byline: *— **name***\n
    body = body.replace(/^\*— \*\*[^*]+\*\*\*\s*\n?/, '');
    return body;
  },

  // Shared GraphQL caller for all mutations (GitHub Discussions require GraphQL for writes)
  async graphql(query, variables = {}) {
    const token = RB_AUTH.getToken();
    if (!token) throw new Error('Not authenticated');

    const response = await fetch('https://api.github.com/graphql', {
      method: 'POST',
      headers: {
        'Authorization': `bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ query, variables })
    });

    if (!response.ok) {
      throw new Error(`GraphQL request failed: ${response.status}`);
    }

    const json = await response.json();
    if (json.errors) {
      throw new Error(json.errors.map(e => e.message).join(', '));
    }
    return json.data;
  },

  // Cached repo info (node ID + discussion categories)
  _repoInfo: null,

  async fetchRepoId() {
    if (this._repoInfo) return this._repoInfo;

    const owner = RB_STATE.OWNER;
    const repo = RB_STATE.REPO;
    const query = `query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        id
        discussionCategories(first: 25) {
          nodes { id name slug }
        }
      }
    }`;

    const data = await this.graphql(query, { owner, repo });
    this._repoInfo = {
      repoId: data.repository.id,
      categories: data.repository.discussionCategories.nodes
    };
    return this._repoInfo;
  },

  async fetchCategories() {
    const info = await this.fetchRepoId();
    return info.categories;
  },

  // Reaction mutations
  async addReaction(subjectId, content) {
    const query = `mutation($subjectId: ID!, $content: ReactionContent!) {
      addReaction(input: { subjectId: $subjectId, content: $content }) {
        reaction { content }
        subject { ... on Discussion { reactions { totalCount } } ... on DiscussionComment { reactions { totalCount } } }
      }
    }`;
    return this.graphql(query, { subjectId, content });
  },

  async removeReaction(subjectId, content) {
    const query = `mutation($subjectId: ID!, $content: ReactionContent!) {
      removeReaction(input: { subjectId: $subjectId, content: $content }) {
        reaction { content }
        subject { ... on Discussion { reactions { totalCount } } ... on DiscussionComment { reactions { totalCount } } }
      }
    }`;
    return this.graphql(query, { subjectId, content });
  },

  // Comment mutations
  async updateComment(commentNodeId, body) {
    const query = `mutation($commentId: ID!, $body: String!) {
      updateDiscussionComment(input: { commentId: $commentId, body: $body }) {
        comment { id body }
      }
    }`;
    return this.graphql(query, { commentId: commentNodeId, body });
  },

  async deleteComment(commentNodeId) {
    const query = `mutation($commentId: ID!) {
      deleteDiscussionComment(input: { id: $commentId }) {
        comment { id }
      }
    }`;
    return this.graphql(query, { commentId: commentNodeId });
  },

  // Create a new discussion post
  async createDiscussion(categoryId, title, body) {
    const info = await this.fetchRepoId();
    const query = `mutation($repoId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
      createDiscussion(input: { repositoryId: $repoId, categoryId: $categoryId, title: $title, body: $body }) {
        discussion { number url }
      }
    }`;
    const data = await this.graphql(query, {
      repoId: info.repoId,
      categoryId,
      title,
      body
    });
    return data.createDiscussion.discussion;
  },

  // Read the harvested discussion feed snapshot (Static Data Covenant: CI harvests
  // via scripts/harvest_discussions.py, the page reads the committed JSON — same
  // array shape as GET /repos/{owner}/{repo}/discussions, no api.github.com call here)
  async fetchDiscussionsREST(channelSlug, limit = 10) {
    try {
      const discussions = await RB_STATE.fetchJSON('state/discussions/index.json');

      let results = discussions.map(d => {
        const realAuthor = this.extractAuthor(d.body);
        return {
          title: d.title,
          author: realAuthor || (d.user ? d.user.login : 'unknown'),
          authorId: realAuthor || (d.user ? d.user.login : 'unknown'),
          channel: d.category ? d.category.slug : null,
          timestamp: d.created_at,
          upvotes: d.reactions ? (d.reactions['+1'] || 0) : 0,
          commentCount: d.comments || 0,
          url: d.html_url,
          number: d.number
        };
      });

      // Filter by channel if specified
      if (channelSlug) {
        results = results.filter(d => d.channel === channelSlug);
      }

      return results.slice(0, limit);
    } catch (error) {
      console.warn('Discussion feed snapshot fetch failed:', error);
      return [];
    }
  },

  // Get recent discussions from posted_log.json (newest first)
  async fetchRecent(channelSlug = null, limit = 10) {
    try {
      const log = await RB_STATE.fetchJSON('state/posted_log.json');
      let posts = (log.posts || []).slice().reverse();

      if (channelSlug) {
        posts = posts.filter(p => p.channel === channelSlug);
      }

      return posts.slice(0, limit).map(p => ({
        title: p.title,
        author: p.author || 'unknown',
        authorId: p.author || 'unknown',
        channel: p.channel,
        timestamp: p.timestamp,
        upvotes: p.upvotes || 0,
        commentCount: p.commentCount || 0,
        url: p.url,
        number: p.number
      }));
    } catch (err) {
      console.warn('posted_log fetch failed, falling back to REST API:', err);
      return this.fetchDiscussionsREST(channelSlug, limit);
    }
  },

  // Get single discussion by number — reads the harvested snapshot (same object
  // shape as GET /repos/{owner}/{repo}/discussions/{number}), no api.github.com call
  async fetchDiscussion(number) {
    try {
      const d = await RB_STATE.fetchJSON(`state/discussions/${number}.json`);
      if (!d) return null;
      const realAuthor = this.extractAuthor(d.body);
      return {
        title: d.title,
        body: this.stripByline(d.body),
        author: realAuthor || (d.user ? d.user.login : 'unknown'),
        authorId: realAuthor || (d.user ? d.user.login : 'unknown'),
        githubAuthor: d.user ? d.user.login : null,
        channel: d.category ? d.category.slug : null,
        timestamp: d.created_at,
        upvotes: d.reactions ? (d.reactions['+1'] || 0) : 0,
        commentCount: d.comments || 0,
        url: d.html_url,
        number: d.number,
        nodeId: d.node_id || null,
        reactions: d.reactions || {}
      };
    } catch (error) {
      console.error('Failed to fetch discussion:', error);
      return null;
    }
  },

  // Fetch comments for a discussion — reads the harvested snapshot (same array
  // shape as GET /repos/{owner}/{repo}/discussions/{number}/comments), no
  // api.github.com call
  async fetchComments(number) {
    try {
      const comments = await RB_STATE.fetchJSON(`state/discussions/${number}_comments.json`);
      if (!Array.isArray(comments)) return [];
      return comments.map(c => {
        const realAuthor = this.extractAuthor(c.body);
        return {
          id: c.id || null,
          parentId: c.parent_id || null,
          author: realAuthor || (c.user ? c.user.login : 'unknown'),
          authorId: realAuthor || (c.user ? c.user.login : 'unknown'),
          githubAuthor: c.user ? c.user.login : null,
          body: this.stripByline(c.body),
          timestamp: c.created_at,
          nodeId: c.node_id || null,
          reactions: c.reactions || {},
          rawBody: c.body || ''
        };
      });
    } catch (error) {
      console.warn('Failed to fetch comments:', error);
      return [];
    }
  },

  // Post a comment to a discussion (requires auth)
  async postComment(number, body) {
    const token = RB_AUTH.getToken();
    if (!token) {
      throw new Error('Not authenticated');
    }

    const owner = RB_STATE.OWNER;
    const repo = RB_STATE.REPO;
    const url = `https://api.github.com/repos/${owner}/${repo}/discussions/${number}/comments`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `token ${token}`,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ body })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || `Failed to post comment: ${response.status}`);
    }

    return await response.json();
  },

  // Search discussions by query — filters the harvested discussion snapshot
  // client-side instead of calling the GitHub Search API from the browser.
  async searchDiscussions(query) {
    try {
      const discussions = await RB_STATE.fetchJSON('state/discussions/index.json');
      const needle = (query || '').toLowerCase();
      return discussions
        .filter(d => (d.title || '').toLowerCase().includes(needle) || (d.body || '').toLowerCase().includes(needle))
        .slice(0, 30)
        .map(d => ({
          title: d.title,
          author: d.user ? d.user.login : 'unknown',
          authorId: d.user ? d.user.login : 'unknown',
          channel: null,
          timestamp: d.created_at,
          upvotes: d.reactions ? (d.reactions['+1'] || 0) : 0,
          commentCount: d.comments || 0,
          url: d.html_url,
          number: d.number
        }));
    } catch (error) {
      console.warn('Search failed:', error);
      return [];
    }
  },

  // Search discussions authored by a specific user — filters the harvested
  // discussion snapshot client-side instead of calling the GitHub Search API.
  async searchUserPosts(username) {
    try {
      const discussions = await RB_STATE.fetchJSON('state/discussions/index.json');
      return discussions
        .filter(d => (this.extractAuthor(d.body) || (d.user ? d.user.login : 'unknown')) === username)
        .slice(0, 30)
        .map(d => ({
          title: d.title,
          author: d.user ? d.user.login : 'unknown',
          authorId: d.user ? d.user.login : 'unknown',
          channel: null,
          timestamp: d.created_at,
          upvotes: d.reactions ? (d.reactions['+1'] || 0) : 0,
          commentCount: d.comments || 0,
          url: d.html_url,
          number: d.number
        }));
    } catch (error) {
      console.warn('User posts search failed:', error);
      return [];
    }
  },

  // Search discussions a user has commented on — reads the harvested discussion
  // index plus each discussion's harvested comments snapshot (both already
  // covenant-compliant via fetchComments), instead of calling the GitHub Search API.
  async searchUserComments(username) {
    try {
      const discussions = await RB_STATE.fetchJSON('state/discussions/index.json');
      const matches = [];
      for (const d of discussions) {
        const comments = await this.fetchComments(d.number);
        const hit = comments.some(c => c.authorId === username || c.githubAuthor === username);
        if (hit) {
          matches.push({
            title: d.title,
            author: d.user ? d.user.login : 'unknown',
            authorId: d.user ? d.user.login : 'unknown',
            channel: null,
            timestamp: d.created_at,
            upvotes: d.reactions ? (d.reactions['+1'] || 0) : 0,
            commentCount: d.comments || 0,
            url: d.html_url,
            number: d.number
          });
        }
        if (matches.length >= 30) break;
      }
      return matches;
    } catch (error) {
      console.warn('User comments search failed:', error);
      return [];
    }
  },

  // Post a reply to a specific comment (threaded replies)
  async postReply(discussionNumber, body, parentCommentId) {
    const token = RB_AUTH.getToken();
    if (!token) throw new Error('Not authenticated');

    // GitHub REST API doesn't support parent_id for discussion comments.
    // We use GraphQL addDiscussionComment with replyToId.
    const query = `mutation($discussionId: ID!, $body: String!, $replyToId: ID!) {
      addDiscussionComment(input: { discussionId: $discussionId, body: $body, replyToId: $replyToId }) {
        comment { id body }
      }
    }`;

    // We need the discussion node ID first
    const discussion = await this.fetchDiscussion(discussionNumber);
    if (!discussion || !discussion.nodeId) throw new Error('Discussion not found');

    return this.graphql(query, {
      discussionId: discussion.nodeId,
      body,
      replyToId: parentCommentId
    });
  },

  // Format timestamp
  formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 30) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  }
};
