(async () => {
  await customElements.whenDefined("ha-panel-lovelace");
  const LitElement = Object.getPrototypeOf(
    customElements.get("ha-panel-lovelace")
  );
  const html = LitElement.prototype.html;
  const css = LitElement.prototype.css;

  class TaskCard extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
        _completing: { type: Object },
        _expandedHistory: { type: Object },
        _expandedDescription: { type: Object },
        _filter: { type: String },
      };
    }

    constructor() {
      super();
      this._completing = {};
      this._expandedHistory = {};
      this._expandedDescription = {};
      this._filter = "all";
    }

    setConfig(config) {
      if (!config.area && !config.areas && !config.entities) {
        throw new Error("Please define 'area', 'areas', or 'entities'");
      }
      this._config = {
        show_history: true,
        default_filter: "all",
        filter_user: "all",
        sort_by: "due_date",
        show_overdue_first: true,
        compact: false,
        show_device_info: true,
        ...config,
      };
      this._filter = this._config.default_filter;
    }

    set hass(hass) {
      this._hass = hass;
      this.requestUpdate();
    }

    get hass() {
      return this._hass;
    }

    getCardSize() {
      const tasks = this._getTaskEntities();
      return 1 + tasks.length * 2 + (this._config.show_history ? 2 : 0);
    }

    static getConfigElement() {
      return document.createElement("task-card-editor");
    }

    static getStubConfig() {
      return { area: "", show_history: true };
    }

    _getTaskEntities() {
      if (!this.hass) return [];

      if (this._config.entities) {
        return this._config.entities
          .map((eid) => {
            const state = this.hass.states[eid];
            return state ? { entityId: eid, state } : null;
          })
          .filter(Boolean);
      }

      const areaList = this._config.areas
        || (this._config.area ? (Array.isArray(this._config.area) ? this._config.area : [this._config.area]) : null);
      if (areaList) {
        return Object.entries(this.hass.states)
          .filter(([eid, state]) => {
            if (!eid.startsWith("sensor.")) return false;
            const attrs = state.attributes;
            return (
              areaList.includes(attrs.area_id) &&
              attrs.interval_days !== undefined &&
              !eid.endsWith("_history")
            );
          })
          .map(([eid, state]) => ({ entityId: eid, state }));
      }

      return [];
    }

    _getDeviceName(deviceId) {
      if (!deviceId || !this.hass || !this.hass.devices) return null;
      const device = this.hass.devices[deviceId];
      if (!device) return null;
      return device.name_by_user || device.name || null;
    }

    _hasMultipleTypes(tasks) {
      let hasTask = false;
      let hasMaintenance = false;
      for (const { state } of tasks) {
        const type = state.attributes.subentry_type;
        if (type === "maintenance") hasMaintenance = true;
        else hasTask = true;
        if (hasTask && hasMaintenance) return true;
      }
      return false;
    }

    _getFilteredTasks(tasks) {
      if (this._filter === "all") return tasks;
      if (this._filter === "maintenance") {
        return tasks.filter(({ state }) => state.attributes.subentry_type === "maintenance");
      }
      return tasks.filter(({ state }) => state.attributes.subentry_type !== "maintenance");
    }

    _getCurrentUserPersonEntity() {
      if (!this.hass?.user?.id) return null;
      const userId = this.hass.user.id;
      for (const [entityId, state] of Object.entries(this.hass.states)) {
        if (!entityId.startsWith("person.")) continue;
        if (state.attributes.user_id === userId) return entityId;
      }
      return null;
    }

    _getUserFilteredTasks(tasks) {
      const filterUser = this._config.filter_user;
      if (!filterUser || filterUser === "all") return tasks;

      let personEntityId;
      const mode = filterUser === "current" || filterUser === "current_turn"
        ? filterUser : null;

      if (mode) {
        personEntityId = this._getCurrentUserPersonEntity();
        if (!personEntityId) return tasks;
      } else {
        personEntityId = filterUser;
      }

      if (filterUser === "current_turn") {
        return tasks.filter(({ state }) =>
          state.attributes.current_assignee === personEntityId
        );
      }

      return tasks.filter(({ state }) => {
        const attrs = state.attributes;
        const assignees = attrs.assignees;
        const inRotation = Array.isArray(assignees) && assignees.includes(personEntityId);
        const isCurrentTurn = attrs.current_assignee === personEntityId;
        return inRotation || isCurrentTurn;
      });
    }

    _getSortedTasks(tasks) {
      const sorted = [...tasks];
      const sortBy = this._config.sort_by || "due_date";

      if (sortBy === "name") {
        sorted.sort((a, b) => {
          const nameA = (a.state.attributes.friendly_name || a.entityId).toLowerCase();
          const nameB = (b.state.attributes.friendly_name || b.entityId).toLowerCase();
          return nameA.localeCompare(nameB);
        });
      } else if (sortBy === "type") {
        sorted.sort((a, b) => {
          const typeA = a.state.attributes.subentry_type === "maintenance" ? 1 : 0;
          const typeB = b.state.attributes.subentry_type === "maintenance" ? 1 : 0;
          if (typeA !== typeB) return typeA - typeB;
          const daysA = parseInt(a.state.state, 10);
          const daysB = parseInt(b.state.state, 10);
          return (isNaN(daysA) ? 999 : daysA) - (isNaN(daysB) ? 999 : daysB);
        });
      } else {
        sorted.sort((a, b) => {
          const daysA = parseInt(a.state.state, 10);
          const daysB = parseInt(b.state.state, 10);
          return (isNaN(daysA) ? 999 : daysA) - (isNaN(daysB) ? 999 : daysB);
        });
      }

      if (this._config.show_overdue_first) {
        sorted.sort((a, b) => {
          const overdueA = a.state.attributes.overdue ? 1 : 0;
          const overdueB = b.state.attributes.overdue ? 1 : 0;
          return overdueB - overdueA;
        });
      }

      return sorted;
    }

    _setFilter(filter) {
      this._filter = filter;
    }

    _getPersonName(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state ? state.attributes.friendly_name || state.state : personEntityId.replace("person.", "").replace(/_/g, " ");
    }

    _getPersonAvatar(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state?.attributes?.entity_picture || null;
    }

    _getHeaderTitle() {
      if (this._config.title) return this._config.title;
      const areaList = this._config.areas
        || (this._config.area ? (Array.isArray(this._config.area) ? this._config.area : [this._config.area]) : null);
      if (!areaList || !this.hass) return "Tasks";
      const haAreas = this.hass.areas;
      if (!haAreas) return "Tasks";
      const names = areaList.map((id) => {
        const a = Object.values(haAreas).find((x) => x.area_id === id);
        return a ? a.name : id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      });
      return names.join(", ") + " Tasks";
    }

    _getDueInfo(state) {
      const attrs = state.attributes;
      const days = parseInt(state.state, 10);
      const overdue = attrs.overdue;

      if (isNaN(days)) return { text: "Not scheduled", cssClass: "due-neutral", icon: "mdi:calendar-question" };
      if (overdue || days < 0) {
        const absDays = Math.abs(days);
        return {
          text: `Overdue ${absDays} day${absDays !== 1 ? "s" : ""}`,
          cssClass: "due-overdue",
          icon: "mdi:alert-circle",
        };
      }
      if (days === 0) return { text: "Due today", cssClass: "due-today", icon: "mdi:calendar-alert" };
      if (days <= 2) return { text: `Due in ${days} day${days !== 1 ? "s" : ""}`, cssClass: "due-soon", icon: "mdi:calendar-clock" };
      return { text: `Due in ${days} days`, cssClass: "due-ok", icon: "mdi:calendar-check" };
    }

    _formatRelativeTime(isoStr) {
      if (!isoStr) return "never";
      const date = new Date(isoStr);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);

      if (diffMins < 1) return "just now";
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays === 1) return "yesterday";
      if (diffDays < 30) return `${diffDays} days ago`;
      const diffMonths = Math.floor(diffDays / 30);
      return `${diffMonths} month${diffMonths !== 1 ? "s" : ""} ago`;
    }

    async _handleComplete(entityId) {
      this._completing = { ...this._completing, [entityId]: true };
      this.requestUpdate();

      try {
        await this.hass.callService("task", "complete_task", {
          entity_id: entityId,
        });
      } catch (e) {
        console.error("Failed to complete task:", e);
      }

      setTimeout(() => {
        this._completing = { ...this._completing, [entityId]: false };
        this.requestUpdate();
      }, 1500);
    }

    _renderAvatar(personEntityId) {
      const avatar = this._getPersonAvatar(personEntityId);
      const name = this._getPersonName(personEntityId);
      if (avatar) {
        return html`<img class="avatar" src="${avatar}" alt="${name}" />`;
      }
      const initial = name ? name.charAt(0).toUpperCase() : "?";
      return html`<span class="avatar avatar-fallback">${initial}</span>`;
    }

    _toggleHistory(entityId) {
      this._expandedHistory = {
        ...this._expandedHistory,
        [entityId]: !this._expandedHistory[entityId],
      };
    }

    _toggleDescription(entityId) {
      this._expandedDescription = {
        ...this._expandedDescription,
        [entityId]: !this._expandedDescription[entityId],
      };
    }

    _renderInlineHistory(entityId) {
      const state = this.hass?.states[entityId];
      const completions = state?.attributes?.recent_completions;
      if (!completions || completions.length === 0) {
        return html`<div class="inline-history"><div class="inline-history-empty">No completions recorded</div></div>`;
      }
      const display = completions.slice(-20).reverse();
      return html`
        <div class="inline-history">
          ${display.map(
            (entry) => html`
              <div class="inline-history-item">
                ${entry.completed_by
                  ? this._renderAvatar(entry.completed_by)
                  : html`<span class="avatar avatar-fallback">?</span>`}
                <span class="inline-history-person">${this._getPersonName(entry.completed_by) || "Unknown user"}</span>
                <span class="inline-history-time">${this._formatRelativeTime(entry.completed_at)}</span>
              </div>
            `
          )}
        </div>
      `;
    }

    _renderTask(entityId, state) {
      const attrs = state.attributes;
      const dueInfo = this._getDueInfo(state);
      const totalCompletions = attrs.total_completions || 0;
      const isCompleting = this._completing[entityId];
      const assigneeName = this._getPersonName(attrs.current_assignee);
      const isMaintenance = attrs.subentry_type === "maintenance";
      const deviceName = isMaintenance ? this._getDeviceName(attrs.device_id) : null;
      const compact = this._config.compact;
      const description = attrs.description;
      const descExpanded = this._expandedDescription[entityId];

      return html`
        <div class="task-item ${isCompleting ? "completing" : ""} ${dueInfo.cssClass} ${isMaintenance ? "maintenance" : ""} ${compact ? "compact" : ""}">
          <div class="task-row-main">
            <div class="task-info">
              <div class="task-name-row">
                <ha-icon .icon=${attrs.icon || "mdi:clipboard-check-outline"} class="task-icon"></ha-icon>
                <span class="task-name">${attrs.friendly_name || state.entity_id}</span>
                ${description ? html`
                  <ha-icon
                    icon=${descExpanded ? "mdi:information" : "mdi:information-outline"}
                    class="desc-toggle-icon ${descExpanded ? "active" : ""}"
                    @click=${() => this._toggleDescription(entityId)}
                  ></ha-icon>
                ` : ""}
                ${isMaintenance && this._config.show_device_info ? html`
                  <span class="maintenance-badge"><ha-icon icon="mdi:wrench" class="maintenance-badge-icon"></ha-icon>${deviceName ? html`<span class="badge-separator">·</span>${deviceName}` : ""}</span>
                ` : ""}
              </div>
              ${descExpanded && description ? html`
                <div class="task-description">${description}</div>
              ` : ""}
              <div class="task-meta-row">
                <span class="assignee-chip">
                ${attrs.current_assignee
                  ? this._renderAvatar(attrs.current_assignee)
                  : html`<ha-icon icon="mdi:account-off" class="avatar avatar-fallback avatar-icon"></ha-icon>`}
                <span class="assignee-name ${!assigneeName ? "unassigned" : ""}">${assigneeName || "Unassigned"}</span>
              </span>
              <span class="meta-dot">·</span>
                <span class="due-badge ${dueInfo.cssClass}">
                  <ha-icon .icon=${dueInfo.icon} class="due-icon"></ha-icon>
                  ${dueInfo.text}
                </span>
              </div>
              ${!compact ? html`
              <div class="task-detail-row">
                <span class="detail-item">
                  <ha-icon icon="mdi:repeat" class="detail-icon"></ha-icon>
                  Every ${attrs.interval_days} day${attrs.interval_days !== 1 ? "s" : ""}
                </span>
                <span class="meta-dot">·</span>
                <span class="detail-item detail-clickable" @click=${() => this._toggleHistory(entityId)}>
                  <ha-icon icon="mdi:check-all" class="detail-icon"></ha-icon>
                  Done ${totalCompletions} time${totalCompletions !== 1 ? "s" : ""}
                  <ha-icon icon=${this._expandedHistory[entityId] ? "mdi:chevron-up" : "mdi:chevron-down"} class="detail-chevron"></ha-icon>
                </span>
                ${attrs.last_completed
                  ? html`
                      <span class="meta-dot">·</span>
                      <span class="detail-item">
                        Last ${this._formatRelativeTime(attrs.last_completed)}
                      </span>
                    `
                  : ""}
              </div>
              ` : ""}
            </div>
            <button
              class="complete-btn ${isCompleting ? "done" : ""}"
              @click=${() => this._handleComplete(entityId)}
              ?disabled=${isCompleting}
            >
              <ha-icon icon=${isCompleting ? "mdi:check-circle" : "mdi:check"} class="btn-icon"></ha-icon>
              <span class="btn-label">${isCompleting ? "Done!" : "Complete"}</span>
            </button>
          </div>
          ${!compact ? html`
          <div class="history-collapse-wrapper ${this._expandedHistory[entityId] ? "expanded" : ""}">
            ${this._expandedHistory[entityId] ? this._renderInlineHistory(entityId) : ""}
          </div>
          ` : ""}
        </div>
      `;
    }

    _renderHistory(tasks) {
      const allRecent = [];

      for (const { entityId, state } of tasks) {
        const completions = state.attributes.recent_completions;
        if (!completions) continue;

        const taskName = state.attributes.friendly_name || entityId;
        for (const entry of completions.slice(-5)) {
          allRecent.push({
            taskName,
            completedAt: entry.completed_at,
            completedBy: entry.completed_by,
          });
        }
      }

      allRecent.sort(
        (a, b) => new Date(b.completedAt) - new Date(a.completedAt)
      );
      const display = allRecent.slice(0, 5);

      if (display.length === 0) {
        return html`
          <div class="history-section">
            <div class="section-header">
              <ha-icon icon="mdi:history" class="section-icon"></ha-icon>
              <span>Recent Activity</span>
            </div>
            <div class="history-empty">No completions recorded yet</div>
          </div>
        `;
      }

      return html`
        <div class="history-section">
          <div class="section-header">
            <ha-icon icon="mdi:history" class="section-icon"></ha-icon>
            <span>Recent Activity</span>
          </div>
          ${display.map(
            (entry) => html`
              <div class="history-item">
                ${entry.completedBy
                  ? html`${this._renderAvatar(entry.completedBy)}`
                  : html`<span class="avatar avatar-fallback">?</span>`}
                <div class="history-text">
                  <span class="history-person">${this._getPersonName(entry.completedBy) || "Unknown user"}</span>
                  completed
                  <span class="history-task">${entry.taskName}</span>
                </div>
                <span class="history-time">${this._formatRelativeTime(entry.completedAt)}</span>
              </div>
            `
          )}
        </div>
      `;
    }

    render() {
      if (!this.hass || !this._config) {
        return html`<ha-card>
          <div class="loading">
            <div class="loading-pulse"></div>
            <span>Loading tasks…</span>
          </div>
        </ha-card>`;
      }

      const allTasks = this._getTaskEntities();
      const showFilters = this._hasMultipleTypes(allTasks);
      const typeFiltered = this._getFilteredTasks(allTasks);
      const filteredTasks = this._getUserFilteredTasks(typeFiltered);
      const tasks = this._getSortedTasks(filteredTasks);
      const headerTitle = this._getHeaderTitle();

      return html`
        <ha-card class="${this._config.compact ? "compact-card" : ""}">
          <div class="card-header">
            <ha-icon icon=${this._config.icon || "mdi:home-floor-1"} class="header-icon"></ha-icon>
            <span class="header-title">${headerTitle}</span>
            <span class="task-count">${tasks.length}</span>
          </div>

          ${showFilters ? html`
          <div class="filter-bar">
            <button class="filter-chip ${this._filter === "all" ? "active" : ""}" @click=${() => this._setFilter("all")}>All</button>
            <button class="filter-chip ${this._filter === "tasks" ? "active" : ""}" @click=${() => this._setFilter("tasks")}>Tasks</button>
            <button class="filter-chip ${this._filter === "maintenance" ? "active" : ""}" @click=${() => this._setFilter("maintenance")}>Maintenance</button>
          </div>
          ` : ""}

          ${tasks.length === 0
            ? html`<div class="empty-state">
                <ha-icon icon="mdi:check-circle-outline" class="empty-icon"></ha-icon>
                <span class="empty-title">All clear!</span>
                <span class="empty-subtitle">${allTasks.length === 0 ? "No tasks configured for this area" : "No matching tasks"}</span>
              </div>`
            : ""}

          <div class="task-list ${this._config.compact ? "compact" : ""}">
            ${tasks.map(({ entityId, state }) => this._renderTask(entityId, state))}
          </div>

          ${this._config.show_history ? this._renderHistory(tasks) : ""}
        </ha-card>
      `;
    }

    static get styles() {
      return css`
        :host {
          --task-card-spacing: 12px;
          --task-card-radius: 12px;
          --task-item-radius: 10px;
        }

        ha-card {
          padding: 0;
          overflow: hidden;
        }

        /* ── Header ── */

        .card-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 16px 16px 12px;
        }

        .header-icon {
          --mdc-icon-size: 22px;
          color: var(--primary-color);
        }

        .header-title {
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color);
          flex: 1;
        }

        .task-count {
          font-size: 12px;
          font-weight: 600;
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 12%, transparent);
          border-radius: 10px;
          padding: 2px 8px;
          min-width: 20px;
          text-align: center;
        }

        /* ── Filter bar ── */

        .filter-bar {
          display: flex;
          gap: 6px;
          padding: 0 16px 10px;
        }

        .filter-chip {
          border: none;
          border-radius: 12px;
          padding: 4px 10px;
          font-size: 11px;
          font-weight: 500;
          font-family: inherit;
          cursor: pointer;
          transition: background 0.2s ease, color 0.2s ease, transform 0.1s ease;
          background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
          color: var(--secondary-text-color);
          height: 24px;
          display: inline-flex;
          align-items: center;
        }

        .filter-chip:hover {
          background: color-mix(in srgb, var(--primary-color) 15%, transparent);
          color: var(--primary-color);
        }

        .filter-chip.active {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }

        .filter-chip:active {
          transform: scale(0.95);
        }

        /* ── Task list ── */

        .task-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 0 var(--task-card-spacing) var(--task-card-spacing);
        }

        .task-list.compact {
          gap: 4px;
        }

        /* ── Task item ── */

        .task-item {
          background: var(--card-background-color, var(--ha-card-background, #fff));
          border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
          border-radius: var(--task-item-radius);
          padding: 12px;
          transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.3s ease;
        }

        .task-item.compact {
          padding: 8px;
        }

        .task-item.compact .task-name {
          font-size: 13px;
        }

        .task-item.compact .task-meta-row,
        .task-item.compact .detail-item,
        .task-item.compact .assignee-name {
          font-size: 11px;
        }

        /* ── Maintenance visual distinction ── */

        .task-item.maintenance {
          border-left: 3px solid var(--info-color, #2196f3);
        }

        .task-item.maintenance.due-overdue {
          border-left: 3px solid var(--error-color, #f44336);
        }

        .task-item.maintenance.due-today,
        .task-item.maintenance.due-soon {
          border-left: 3px solid var(--warning-color, #ff9800);
        }

        .maintenance-badge {
          display: inline-flex;
          align-items: center;
          background: color-mix(in srgb, var(--info-color, #2196f3) 12%, transparent);
          color: var(--info-color, #2196f3);
          border-radius: 6px;
          padding: 2px 6px;
          font-size: 10px;
          font-weight: 500;
          flex-shrink: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 200px;
        }

        .maintenance-badge-icon {
          --mdc-icon-size: 13px;
          color: var(--info-color, #2196f3);
        }

        .badge-separator {
          margin: 0 4px;
          opacity: 0.5;
        }

        .task-item:hover {
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        }

        .task-item.completing {
          animation: completeFlash 0.5s ease;
        }

        @keyframes completeFlash {
          0% { transform: scale(1); }
          30% { transform: scale(0.97); background: color-mix(in srgb, var(--success-color, #4caf50) 12%, var(--card-background-color, #fff)); }
          100% { transform: scale(1); }
        }

        .task-item.due-overdue {
          border-left: 3px solid var(--error-color, #f44336);
        }

        .task-item.due-today {
          border-left: 3px solid var(--warning-color, #ff9800);
        }

        .task-item.due-soon {
          border-left: 3px solid var(--warning-color, #ff9800);
        }

        /* ── Task main row ── */

        .task-row-main {
          display: flex;
          align-items: flex-start;
          gap: 12px;
        }

        .task-info {
          flex: 1;
          min-width: 0;
        }

        .task-name-row {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 4px;
        }

        .task-icon {
          --mdc-icon-size: 18px;
          color: var(--primary-color);
          flex-shrink: 0;
        }

        .task-name {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        /* ── Description toggle + text ── */

        .desc-toggle-icon {
          --mdc-icon-size: 16px;
          color: var(--secondary-text-color);
          opacity: 0.5;
          cursor: pointer;
          flex-shrink: 0;
          border-radius: 50%;
          transition: opacity 0.15s ease, color 0.15s ease;
        }

        .desc-toggle-icon:hover {
          opacity: 0.85;
          color: var(--primary-color);
        }

        .desc-toggle-icon.active {
          opacity: 0.85;
          color: var(--primary-color);
        }

        .task-description {
          font-size: 12px;
          line-height: 1.4;
          color: var(--secondary-text-color);
          background: color-mix(in srgb, var(--primary-color) 5%, transparent);
          border-radius: 6px;
          padding: 6px 8px;
          margin: 2px 0 4px 24px;
          white-space: pre-line;
          word-break: break-word;
        }

        /* ── Meta row (assignee + due) ── */

        .task-meta-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
          margin-bottom: 4px;
        }

        .meta-dot {
          color: var(--secondary-text-color);
          font-size: 11px;
          opacity: 0.5;
        }

        .assignee-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }

        .avatar {
          width: 20px;
          height: 20px;
          border-radius: 50%;
          object-fit: cover;
          flex-shrink: 0;
        }

        .avatar-fallback {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
          color: var(--primary-color);
          font-size: 11px;
          font-weight: 600;
        }

        .avatar-icon {
          --mdc-icon-size: 14px;
          border-radius: 50%;
        }

        .assignee-name {
          font-size: 12px;
          color: var(--primary-text-color);
          font-weight: 500;
        }

        .assignee-name.unassigned {
          color: var(--secondary-text-color);
          font-style: italic;
          font-weight: 400;
        }

        /* ── Due badge ── */

        .due-badge {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          font-size: 12px;
          font-weight: 500;
          padding: 1px 6px;
          border-radius: 6px;
        }

        .due-icon {
          --mdc-icon-size: 14px;
        }

        .due-ok {
          color: var(--success-color, #4caf50);
        }

        .due-soon {
          color: var(--warning-color, #ff9800);
        }

        .due-today {
          color: var(--warning-color, #ff9800);
          font-weight: 600;
        }

        .due-overdue {
          color: var(--error-color, #f44336);
          font-weight: 600;
        }

        .due-neutral {
          color: var(--secondary-text-color);
        }

        /* ── Detail row ── */

        .task-detail-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }

        .detail-item {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          font-size: 11px;
          color: var(--secondary-text-color);
        }

        .detail-icon {
          --mdc-icon-size: 13px;
          color: var(--secondary-text-color);
          opacity: 0.7;
        }

        .detail-clickable {
          cursor: pointer;
          border-radius: 4px;
          padding: 1px 4px;
          margin: -1px -4px;
          transition: background 0.15s ease;
        }

        .detail-clickable:hover {
          background: color-mix(in srgb, var(--primary-color) 8%, transparent);
          text-decoration: underline;
        }

        .detail-chevron {
          --mdc-icon-size: 14px;
          opacity: 0.5;
          margin-left: -1px;
        }

        /* ── History collapse wrapper ── */

        .history-collapse-wrapper {
          overflow: hidden;
          max-height: 0;
          opacity: 0;
          transition: max-height 0.3s ease, opacity 0.2s ease;
        }

        .history-collapse-wrapper.expanded {
          max-height: 600px;
          opacity: 1;
        }

        /* ── Inline history (expandable per-task) ── */

        .inline-history {
          border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.06));
          margin-top: 8px;
          padding-top: 6px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .inline-history-item {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 3px 0;
        }

        .inline-history-person {
          flex: 1;
          font-size: 12px;
          font-weight: 500;
          color: var(--primary-text-color);
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .inline-history-time {
          font-size: 11px;
          color: var(--secondary-text-color);
          opacity: 0.7;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .inline-history-empty {
          font-size: 12px;
          color: var(--secondary-text-color);
          opacity: 0.6;
          padding: 4px 0;
        }

        /* ── Complete button ── */

        .complete-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 12px;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          font-size: 12px;
          font-weight: 600;
          font-family: inherit;
          white-space: nowrap;
          flex-shrink: 0;
          align-self: center;
          transition: background 0.2s ease, color 0.2s ease, transform 0.15s ease;
          background: color-mix(in srgb, var(--primary-color) 12%, transparent);
          color: var(--primary-color);
        }

        .complete-btn:hover:not(:disabled) {
          background: color-mix(in srgb, var(--primary-color) 22%, transparent);
          transform: scale(1.03);
        }

        .complete-btn:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .complete-btn:active:not(:disabled) {
          transform: scale(0.95);
          background: color-mix(in srgb, var(--primary-color) 30%, transparent);
        }

        .complete-btn.done {
          background: var(--success-color, #4caf50);
          color: #fff;
          pointer-events: none;
        }

        .complete-btn:disabled {
          cursor: default;
        }

        .btn-icon {
          --mdc-icon-size: 16px;
        }

        .btn-label {
          display: none;
        }

        @media (min-width: 400px) {
          .btn-label {
            display: inline;
          }
        }

        /* ── History section ── */

        .history-section {
          border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
          padding: var(--task-card-spacing);
        }

        .section-header {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 13px;
          font-weight: 500;
          color: var(--secondary-text-color);
          margin-bottom: 8px;
        }

        .section-icon {
          --mdc-icon-size: 16px;
        }

        .history-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 4px 0;
        }

        .history-text {
          flex: 1;
          font-size: 12px;
          color: var(--secondary-text-color);
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .history-person {
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .history-task {
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .history-time {
          font-size: 11px;
          color: var(--secondary-text-color);
          opacity: 0.7;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .history-empty {
          font-size: 12px;
          color: var(--secondary-text-color);
          opacity: 0.6;
          padding: 4px 0;
        }

        /* ── Empty + loading states ── */

        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          padding: 32px 16px;
          color: var(--secondary-text-color);
        }

        .empty-icon {
          --mdc-icon-size: 48px;
          opacity: 0.25;
          margin-bottom: 4px;
          color: var(--success-color, #4caf50);
        }

        .empty-title {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .empty-subtitle {
          font-size: 12px;
          opacity: 0.7;
        }

        .loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          padding: 32px 16px;
          color: var(--secondary-text-color);
          font-size: 13px;
        }

        .loading-pulse {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--primary-color) 15%, transparent);
          animation: pulse 1.2s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { transform: scale(0.9); opacity: 0.5; }
          50% { transform: scale(1.1); opacity: 1; }
        }
      `;
    }
  }

  customElements.define("task-card", TaskCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "task-card",
    name: "Task Card",
    description: "Display and manage household tasks",
    preview: true,
    documentationURL: "https://github.com/home-assistant/ha-task",
  });

  // ─────────────────────────────────────────────────────────
  // TaskCardEditor — visual config editor for TaskCard
  // ─────────────────────────────────────────────────────────

  class TaskCardEditor extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
      };
    }

    setConfig(config) {
      this._config = {
        show_history: true,
        show_calendar: false,
        default_filter: "all",
        filter_user: "all",
        sort_by: "due_date",
        show_overdue_first: true,
        compact: false,
        show_device_info: true,
        ...config,
      };
    }

    _fireChanged() {
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        })
      );
    }

    _valueChanged(key, ev) {
      if (!this._config) return;
      const target = ev.target;
      const value =
        target.checked !== undefined ? target.checked : target.value;
      this._config = { ...this._config, [key]: value };
      this._fireChanged();
    }

    _schemaChanged(ev) {
      this._config = { ...this._config, ...ev.detail.value };
      this._fireChanged();
    }

    render() {
      if (!this._config) return html``;

      const personOptions = [
        { value: "all", label: "All Users" },
        { value: "current_turn", label: "My Turn" },
        { value: "current", label: "In Rotation" },
      ];
      if (this.hass) {
        for (const [eid, state] of Object.entries(this.hass.states)) {
          if (!eid.startsWith("person.")) continue;
          personOptions.push({
            value: eid,
            label: state.attributes.friendly_name || eid.replace("person.", "").replace(/_/g, " "),
          });
        }
      }

      const schema = [
        { name: "areas", selector: { area: { multiple: true } } },
        { name: "title", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
        {
          name: "default_filter",
          selector: {
            select: {
              options: [
                { value: "all", label: "All" },
                { value: "tasks", label: "Tasks Only" },
                { value: "maintenance", label: "Maintenance Only" },
              ],
              mode: "dropdown",
            },
          },
        },
        {
          name: "filter_user",
          selector: {
            select: {
              options: personOptions,
              mode: "dropdown",
            },
          },
        },
        {
          name: "sort_by",
          selector: {
            select: {
              options: [
                { value: "due_date", label: "Due Date" },
                { value: "name", label: "Name" },
                { value: "type", label: "Type" },
              ],
              mode: "dropdown",
            },
          },
        },
        {
          name: "show_overdue_first",
          selector: { boolean: {} },
        },
        {
          name: "compact",
          selector: { boolean: {} },
        },
        {
          name: "show_device_info",
          selector: { boolean: {} },
        },
        {
          name: "show_history",
          selector: { boolean: {} },
        },
      ];

      return html`
        <ha-form
          .hass=${this.hass}
          .data=${this._config}
          .schema=${schema}
          .computeLabel=${(s) => {
            const labels = {
              areas: "Areas",
              title: "Title (optional, replaces default)",
              icon: "Icon (optional)",
              show_history: "Show recent activity",
              default_filter: "Default filter",
              filter_user: "Filter by user",
              sort_by: "Sort by",
              show_overdue_first: "Pin overdue items to top",
              compact: "Compact mode",
              show_device_info: "Show device info for maintenance",
            };
            return labels[s.name] || s.name;
          }}
          @value-changed=${this._schemaChanged}
        ></ha-form>
      `;
    }

    static get styles() {
      return css`
        ha-form {
          display: block;
          padding: 16px;
        }

        .switch-row {
          display: flex;
          align-items: center;
        }

        ha-formfield {
          display: flex;
          align-items: center;
          --mdc-theme-text-primary-on-background: var(--primary-text-color);
        }
      `;
    }
  }

  customElements.define("task-card-editor", TaskCardEditor);

  // ─────────────────────────────────────────────────────────
  // TaskSingleCard — standalone card for a single task entity
  // ─────────────────────────────────────────────────────────

  class TaskSingleCard extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
        _completing: { type: Boolean },
        _expandedHistory: { type: Boolean },
        _expandedDescription: { type: Boolean },
      };
    }

    constructor() {
      super();
      this._completing = false;
      this._expandedHistory = false;
      this._expandedDescription = false;
    }

    setConfig(config) {
      if (!config.device && !config.entity) {
        throw new Error("Please define 'device' or 'entity'");
      }
      this._config = { show_device_info: true, ...config };
    }

    set hass(hass) {
      this._hass = hass;
      this.requestUpdate();
    }

    get hass() {
      return this._hass;
    }

    getCardSize() {
      return 3;
    }

    static getConfigElement() {
      return document.createElement("task-single-card-editor");
    }

    static getStubConfig() {
      return { device: "" };
    }

    _getTaskSensor() {
      if (this._config.entity) return this._config.entity;
      const cfg = this._config.device;
      if (!cfg || !this.hass) return null;
      const slug = cfg.toLowerCase().replace(/\s+/g, "_");
      for (const [entityId, state] of Object.entries(this.hass.states)) {
        if (!entityId.startsWith("sensor.")) continue;
        if (state.attributes?.interval_days === undefined) continue;
        const name = (state.attributes.friendly_name || "").toLowerCase().replace(/\s+/g, "_");
        if (name === slug || entityId === cfg || entityId.endsWith(`_${slug}`)) {
          return entityId;
        }
      }
      return null;
    }

    _getDeviceName(deviceId) {
      if (!deviceId || !this.hass || !this.hass.devices) return null;
      const device = this.hass.devices[deviceId];
      if (!device) return null;
      return device.name_by_user || device.name || null;
    }

    _getPersonName(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state ? state.attributes.friendly_name || state.state : personEntityId.replace("person.", "").replace(/_/g, " ");
    }

    _getPersonAvatar(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state?.attributes?.entity_picture || null;
    }

    _renderAvatar(personEntityId) {
      const avatar = this._getPersonAvatar(personEntityId);
      const name = this._getPersonName(personEntityId);
      if (avatar) {
        return html`<img class="avatar" src="${avatar}" alt="${name}" />`;
      }
      const initial = name ? name.charAt(0).toUpperCase() : "?";
      return html`<span class="avatar avatar-fallback">${initial}</span>`;
    }

    _getDueInfo(state) {
      const attrs = state.attributes;
      const days = parseInt(state.state, 10);
      const overdue = attrs.overdue;
      if (isNaN(days)) return { text: "Not scheduled", cssClass: "due-neutral", icon: "mdi:calendar-question" };
      if (overdue || days < 0) {
        const absDays = Math.abs(days);
        return { text: `Overdue ${absDays} day${absDays !== 1 ? "s" : ""}`, cssClass: "due-overdue", icon: "mdi:alert-circle" };
      }
      if (days === 0) return { text: "Due today", cssClass: "due-today", icon: "mdi:calendar-alert" };
      if (days <= 2) return { text: `Due in ${days} day${days !== 1 ? "s" : ""}`, cssClass: "due-soon", icon: "mdi:calendar-clock" };
      return { text: `Due in ${days} days`, cssClass: "due-ok", icon: "mdi:calendar-check" };
    }

    _formatRelativeTime(isoStr) {
      if (!isoStr) return "never";
      const date = new Date(isoStr);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);
      if (diffMins < 1) return "just now";
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays === 1) return "yesterday";
      if (diffDays < 30) return `${diffDays} days ago`;
      const diffMonths = Math.floor(diffDays / 30);
      return `${diffMonths} month${diffMonths !== 1 ? "s" : ""} ago`;
    }

    async _handleComplete() {
      const entityId = this._getTaskSensor();
      if (!entityId) return;
      this._completing = true;
      this.requestUpdate();
      try {
        await this.hass.callService("task", "complete_task", {
          entity_id: entityId,
        });
      } catch (e) {
        console.error("Failed to complete task:", e);
      }
      setTimeout(() => {
        this._completing = false;
        this.requestUpdate();
      }, 1500);
    }

    _toggleHistory() {
      this._expandedHistory = !this._expandedHistory;
    }

    _toggleDescription() {
      this._expandedDescription = !this._expandedDescription;
    }

    _renderInlineHistory() {
      const entityId = this._getTaskSensor();
      const state = entityId ? this.hass?.states[entityId] : null;
      const completions = state?.attributes?.recent_completions;
      if (!completions || completions.length === 0) {
        return html`<div class="inline-history"><div class="inline-history-empty">No completions recorded</div></div>`;
      }
      const display = completions.slice(-20).reverse();
      return html`
        <div class="inline-history">
          ${display.map(
            (entry) => html`
              <div class="inline-history-item">
                ${entry.completed_by
                  ? this._renderAvatar(entry.completed_by)
                  : html`<span class="avatar avatar-fallback">?</span>`}
                <span class="inline-history-person">${this._getPersonName(entry.completed_by) || "Unknown user"}</span>
                <span class="inline-history-time">${this._formatRelativeTime(entry.completed_at)}</span>
              </div>
            `
          )}
        </div>
      `;
    }

    render() {
      if (!this.hass || !this._config) {
        return html`<ha-card>
          <div class="loading">
            <div class="loading-pulse"></div>
            <span>Loading task…</span>
          </div>
        </ha-card>`;
      }

      const entityId = this._getTaskSensor();
      if (!entityId) {
        return html`<ha-card>
          <div class="error-state">
            <ha-icon icon="mdi:magnify-close" class="error-icon"></ha-icon>
            <span class="error-title">Task not found</span>
            <span class="error-subtitle">No sensor matches "${this._config.device || this._config.entity}"</span>
          </div>
        </ha-card>`;
      }
      const state = this.hass.states[entityId];
      if (!state) {
        return html`<ha-card>
          <div class="error-state">
            <ha-icon icon="mdi:alert-circle-outline" class="error-icon"></ha-icon>
            <span class="error-title">Entity unavailable</span>
            <span class="error-subtitle">${entityId}</span>
          </div>
        </ha-card>`;
      }

      const attrs = state.attributes;
      const dueInfo = this._getDueInfo(state);
      const totalCompletions = attrs.total_completions || 0;
      const assigneeName = this._getPersonName(attrs.current_assignee);
      const isMaintenance = attrs.subentry_type === "maintenance";
      const deviceName = isMaintenance ? this._getDeviceName(attrs.device_id) : null;
      const description = attrs.description;

      return html`
        <ha-card class="${this._completing ? "completing" : ""}">
          <div class="single-header">
            <ha-icon .icon=${attrs.icon || "mdi:clipboard-check-outline"} class="single-task-icon"></ha-icon>
            <span class="single-task-name">${attrs.friendly_name || entityId}</span>
            ${description ? html`
              <ha-icon
                icon=${this._expandedDescription ? "mdi:information" : "mdi:information-outline"}
                class="desc-toggle-icon ${this._expandedDescription ? "active" : ""}"
                @click=${() => this._toggleDescription()}
              ></ha-icon>
            ` : ""}
            ${isMaintenance && this._config.show_device_info ? html`
              <span class="single-maintenance-badge"><ha-icon icon="mdi:wrench" class="maintenance-badge-icon"></ha-icon>${deviceName ? html`<span class="badge-separator">·</span>${deviceName}` : ""}</span>
            ` : ""}
          </div>

          ${this._expandedDescription && description ? html`
            <div class="single-description">${description}</div>
          ` : ""}

          <div class="single-body">
            <div class="single-row">
              <span class="assignee-chip">
                ${attrs.current_assignee
                  ? this._renderAvatar(attrs.current_assignee)
                  : html`<ha-icon icon="mdi:account-off" class="avatar avatar-fallback avatar-icon"></ha-icon>`}
                <span class="assignee-name ${!assigneeName ? "unassigned" : ""}">${assigneeName || "Unassigned"}</span>
              </span>
              <span class="meta-dot">·</span>
              <span class="due-badge ${dueInfo.cssClass}">
                <ha-icon .icon=${dueInfo.icon} class="due-icon"></ha-icon>
                ${dueInfo.text}
              </span>
            </div>

            <div class="single-details">
              <span class="detail-item">
                <ha-icon icon="mdi:repeat" class="detail-icon"></ha-icon>
                Every ${attrs.interval_days} day${attrs.interval_days !== 1 ? "s" : ""}
              </span>
              <span class="meta-dot">·</span>
              <span class="detail-item detail-clickable" @click=${() => this._toggleHistory()}>
                <ha-icon icon="mdi:check-all" class="detail-icon"></ha-icon>
                Done ${totalCompletions} time${totalCompletions !== 1 ? "s" : ""}
                <ha-icon icon=${this._expandedHistory ? "mdi:chevron-up" : "mdi:chevron-down"} class="detail-chevron"></ha-icon>
              </span>
              ${attrs.last_completed
                ? html`
                    <span class="meta-dot">·</span>
                    <span class="detail-item">
                      Last ${this._formatRelativeTime(attrs.last_completed)}
                    </span>
                  `
                : ""}
            </div>

            <div class="history-collapse-wrapper ${this._expandedHistory ? "expanded" : ""}">
              ${this._expandedHistory ? this._renderInlineHistory() : ""}
            </div>
          </div>

          <div class="single-footer">
            <button
              class="complete-btn single-complete-btn ${this._completing ? "done" : ""}"
              @click=${() => this._handleComplete()}
              ?disabled=${this._completing}
            >
              <ha-icon icon=${this._completing ? "mdi:check-circle" : "mdi:check"} class="btn-icon"></ha-icon>
              <span>${this._completing ? "Done!" : "Complete"}</span>
            </button>
          </div>
        </ha-card>
      `;
    }

    static get styles() {
      return css`
        :host {
          --task-card-spacing: 12px;
          --task-card-radius: 12px;
          --task-item-radius: 10px;
        }

        ha-card {
          padding: 0;
          overflow: hidden;
          transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        ha-card.completing {
          animation: completeFlash 0.5s ease;
        }

        @keyframes completeFlash {
          0% { transform: scale(1); }
          30% { transform: scale(0.98); background: color-mix(in srgb, var(--success-color, #4caf50) 12%, var(--card-background-color, #fff)); }
          100% { transform: scale(1); }
        }

        /* ── Header ── */

        .single-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 14px 16px 0;
        }

        .single-task-icon {
          --mdc-icon-size: 22px;
          color: var(--primary-color);
          flex-shrink: 0;
        }

        .single-task-name {
          font-size: 15px;
          font-weight: 600;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          flex: 1;
          min-width: 0;
        }

        .desc-toggle-icon {
          --mdc-icon-size: 16px;
          color: var(--secondary-text-color);
          opacity: 0.5;
          cursor: pointer;
          flex-shrink: 0;
          border-radius: 50%;
          transition: opacity 0.15s ease, color 0.15s ease;
        }

        .desc-toggle-icon:hover {
          opacity: 0.85;
          color: var(--primary-color);
        }

        .desc-toggle-icon.active {
          opacity: 0.85;
          color: var(--primary-color);
        }

        .single-description {
          font-size: 12px;
          line-height: 1.4;
          color: var(--secondary-text-color);
          background: color-mix(in srgb, var(--primary-color) 5%, transparent);
          border-radius: 6px;
          padding: 6px 10px;
          margin: 0 16px;
          white-space: pre-line;
          word-break: break-word;
        }

        .single-maintenance-badge {
          display: inline-flex;
          align-items: center;
          background: color-mix(in srgb, var(--info-color, #2196f3) 12%, transparent);
          color: var(--info-color, #2196f3);
          border-radius: 6px;
          padding: 2px 6px;
          font-size: 10px;
          font-weight: 500;
          flex-shrink: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 200px;
        }

        .maintenance-badge-icon {
          --mdc-icon-size: 13px;
          color: var(--info-color, #2196f3);
        }

        .badge-separator {
          margin: 0 4px;
          opacity: 0.5;
        }

        /* ── Body ── */

        .single-body {
          padding: 10px 16px;
        }

        .single-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
          margin-bottom: 6px;
        }

        .single-details {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }

        /* ── Shared styles (match TaskCard) ── */

        .meta-dot {
          color: var(--secondary-text-color);
          font-size: 11px;
          opacity: 0.5;
        }

        .assignee-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }

        .avatar {
          width: 20px;
          height: 20px;
          border-radius: 50%;
          object-fit: cover;
          flex-shrink: 0;
        }

        .avatar-fallback {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
          color: var(--primary-color);
          font-size: 11px;
          font-weight: 600;
        }

        .avatar-icon {
          --mdc-icon-size: 14px;
          border-radius: 50%;
        }

        .assignee-name {
          font-size: 12px;
          color: var(--primary-text-color);
          font-weight: 500;
        }

        .assignee-name.unassigned {
          color: var(--secondary-text-color);
          font-style: italic;
          font-weight: 400;
        }

        .due-badge {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          font-size: 12px;
          font-weight: 500;
          padding: 1px 6px;
          border-radius: 6px;
        }

        .due-icon { --mdc-icon-size: 14px; }
        .due-ok { color: var(--success-color, #4caf50); }
        .due-soon { color: var(--warning-color, #ff9800); }
        .due-today { color: var(--warning-color, #ff9800); font-weight: 600; }
        .due-overdue { color: var(--error-color, #f44336); font-weight: 600; }
        .due-neutral { color: var(--secondary-text-color); }

        .detail-item {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          font-size: 11px;
          color: var(--secondary-text-color);
        }

        .detail-icon {
          --mdc-icon-size: 13px;
          color: var(--secondary-text-color);
          opacity: 0.7;
        }

        .detail-clickable {
          cursor: pointer;
          border-radius: 4px;
          padding: 1px 4px;
          margin: -1px -4px;
          transition: background 0.15s ease;
        }

        .detail-clickable:hover {
          background: color-mix(in srgb, var(--primary-color) 8%, transparent);
          text-decoration: underline;
        }

        .detail-chevron {
          --mdc-icon-size: 14px;
          opacity: 0.5;
          margin-left: -1px;
        }

        /* ── History collapse wrapper ── */

        .history-collapse-wrapper {
          overflow: hidden;
          max-height: 0;
          opacity: 0;
          transition: max-height 0.3s ease, opacity 0.2s ease;
        }

        .history-collapse-wrapper.expanded {
          max-height: 600px;
          opacity: 1;
        }

        /* ── Inline history ── */

        .inline-history {
          border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.06));
          margin-top: 8px;
          padding-top: 6px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .inline-history-item {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 3px 0;
        }

        .inline-history-person {
          flex: 1;
          font-size: 12px;
          font-weight: 500;
          color: var(--primary-text-color);
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .inline-history-time {
          font-size: 11px;
          color: var(--secondary-text-color);
          opacity: 0.7;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .inline-history-empty {
          font-size: 12px;
          color: var(--secondary-text-color);
          opacity: 0.6;
          padding: 4px 0;
        }

        /* ── Footer / Complete button ── */

        .single-footer {
          padding: 0 16px 14px;
        }

        .complete-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 6px 12px;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          font-size: 12px;
          font-weight: 600;
          font-family: inherit;
          white-space: nowrap;
          transition: background 0.2s ease, color 0.2s ease, transform 0.15s ease;
          background: color-mix(in srgb, var(--primary-color) 12%, transparent);
          color: var(--primary-color);
        }

        .complete-btn:hover:not(:disabled) {
          background: color-mix(in srgb, var(--primary-color) 22%, transparent);
          transform: scale(1.03);
        }

        .complete-btn:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .complete-btn:active:not(:disabled) {
          transform: scale(0.95);
          background: color-mix(in srgb, var(--primary-color) 30%, transparent);
        }

        .complete-btn.done {
          background: var(--success-color, #4caf50);
          color: #fff;
          pointer-events: none;
        }

        .complete-btn:disabled { cursor: default; }

        .btn-icon { --mdc-icon-size: 16px; }

        .single-complete-btn {
          width: 100%;
          justify-content: center;
          padding: 8px 16px;
          font-size: 13px;
        }

        /* ── Loading + error states ── */

        .loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          padding: 32px 16px;
          color: var(--secondary-text-color);
          font-size: 13px;
        }

        .loading-pulse {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--primary-color) 15%, transparent);
          animation: pulse 1.2s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { transform: scale(0.9); opacity: 0.5; }
          50% { transform: scale(1.1); opacity: 1; }
        }

        .error-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          padding: 24px 16px;
          text-align: center;
        }

        .error-icon {
          --mdc-icon-size: 36px;
          color: var(--secondary-text-color);
          opacity: 0.4;
          margin-bottom: 4px;
        }

        .error-title {
          font-size: 13px;
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .error-subtitle {
          font-size: 12px;
          color: var(--secondary-text-color);
          opacity: 0.7;
          word-break: break-all;
        }
      `;
    }
  }

  customElements.define("task-single-card", TaskSingleCard);

  window.customCards.push({
    type: "task-single-card",
    name: "Task Single Card",
    description: "Display a single household task",
    preview: true,
  });

  // ─────────────────────────────────────────────────────────
  // TaskSingleCardEditor — visual config editor for TaskSingleCard
  // ─────────────────────────────────────────────────────────

  class TaskSingleCardEditor extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
      };
    }

    setConfig(config) {
      this._config = { ...config };
    }

    _fireChanged() {
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        })
      );
    }

    _schemaChanged(ev) {
      this._config = { ...this._config, ...ev.detail.value };
      this._fireChanged();
    }

    render() {
      if (!this._config) return html``;

      const schema = [
        {
          name: "entity",
          selector: {
            entity: {
              filter: [
                { integration: "task", domain: "sensor" },
              ],
            },
          },
        },
      ];

      return html`
        <ha-form
          .hass=${this.hass}
          .data=${this._config}
          .schema=${schema}
          .computeLabel=${() => "Task"}
          @value-changed=${this._schemaChanged}
        ></ha-form>
      `;
    }

    static get styles() {
      return css`
        ha-form {
          display: block;
          padding: 16px;
        }
      `;
    }
  }

  customElements.define("task-single-card-editor", TaskSingleCardEditor);

  // ─────────────────────────────────────────────────────────
  // TaskActivityCard — recent activity feed across areas
  // ─────────────────────────────────────────────────────────

  class TaskActivityCard extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
      };
    }

    setConfig(config) {
      if (!config.area && !config.areas) {
        throw new Error("Please define 'area' or 'areas'");
      }
      this._config = {
        title: "",
        icon: "mdi:history",
        max_items: 15,
        show_task_type: true,
        ...config,
      };
    }

    set hass(hass) {
      this._hass = hass;
      this.requestUpdate();
    }

    get hass() {
      return this._hass;
    }

    getCardSize() {
      return 4;
    }

    static getConfigElement() {
      return document.createElement("task-activity-card-editor");
    }

    static getStubConfig() {
      return { area: "", max_items: 15 };
    }

    _getAreaList() {
      return this._config.areas
        || (this._config.area ? (Array.isArray(this._config.area) ? this._config.area : [this._config.area]) : null);
    }

    _getTaskEntities() {
      if (!this.hass) return [];
      const areaList = this._getAreaList();
      if (!areaList) return [];
      return Object.entries(this.hass.states)
        .filter(([eid, state]) => {
          if (!eid.startsWith("sensor.")) return false;
          const attrs = state.attributes;
          return (
            areaList.includes(attrs.area_id) &&
            attrs.interval_days !== undefined &&
            !eid.endsWith("_history")
          );
        })
        .map(([eid, state]) => ({ entityId: eid, state }));
    }

    _getPersonName(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state ? state.attributes.friendly_name || state.state : personEntityId.replace("person.", "").replace(/_/g, " ");
    }

    _getPersonAvatar(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state?.attributes?.entity_picture || null;
    }

    _renderAvatar(personEntityId, size) {
      const avatar = this._getPersonAvatar(personEntityId);
      const name = this._getPersonName(personEntityId);
      const cls = size === "small" ? "avatar" : "avatar";
      if (avatar) {
        return html`<img class="${cls}" src="${avatar}" alt="${name}" />`;
      }
      const initial = name ? name.charAt(0).toUpperCase() : "?";
      return html`<span class="${cls} avatar-fallback">${initial}</span>`;
    }

    _formatRelativeTime(isoStr) {
      if (!isoStr) return "never";
      const date = new Date(isoStr);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);
      if (diffMins < 1) return "just now";
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays === 1) return "yesterday";
      if (diffDays < 30) return `${diffDays} days ago`;
      const diffMonths = Math.floor(diffDays / 30);
      return `${diffMonths} month${diffMonths !== 1 ? "s" : ""} ago`;
    }

    _getHeaderTitle() {
      if (this._config.title) return this._config.title;
      return "Recent Activity";
    }

    _getDayLabel(date) {
      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      const diffDays = Math.round((today - target) / 86400000);
      if (diffDays === 0) return "Today";
      if (diffDays === 1) return "Yesterday";
      return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }

    _getActivityItems() {
      const tasks = this._getTaskEntities();
      const items = [];

      for (const { entityId, state } of tasks) {
        const completions = state.attributes.recent_completions;
        if (!completions) continue;
        const taskName = state.attributes.friendly_name || entityId;
        const subentryType = state.attributes.subentry_type;
        for (const entry of completions) {
          items.push({
            taskName,
            completedAt: entry.completed_at,
            completedBy: entry.completed_by,
            subentryType,
          });
        }
      }

      items.sort((a, b) => new Date(b.completedAt) - new Date(a.completedAt));
      return items.slice(0, this._config.max_items);
    }

    render() {
      if (!this.hass || !this._config) {
        return html`<ha-card>
          <div class="loading">
            <div class="loading-pulse"></div>
            <span>Loading activity…</span>
          </div>
        </ha-card>`;
      }

      const items = this._getActivityItems();
      const title = this._getHeaderTitle();

      if (items.length === 0) {
        return html`
          <ha-card>
            <div class="card-header">
              <ha-icon icon=${this._config.icon || "mdi:history"} class="header-icon"></ha-icon>
              <span class="header-title">${title}</span>
            </div>
            <div class="empty-state">
              <ha-icon icon="mdi:clock-outline" class="empty-icon"></ha-icon>
              <span class="empty-title">No activity recorded yet</span>
              <span class="empty-subtitle">Completions will appear here</span>
            </div>
          </ha-card>
        `;
      }

      const grouped = [];
      let currentDay = null;
      for (const item of items) {
        const date = new Date(item.completedAt);
        const dayLabel = this._getDayLabel(date);
        if (dayLabel !== currentDay) {
          currentDay = dayLabel;
          grouped.push({ type: "separator", label: dayLabel });
        }
        grouped.push({ type: "item", ...item });
      }

      return html`
        <ha-card>
          <div class="card-header">
            <ha-icon icon=${this._config.icon || "mdi:history"} class="header-icon"></ha-icon>
            <span class="header-title">${title}</span>
            <span class="item-count">${items.length}</span>
          </div>
          <div class="activity-list">
            ${grouped.map((entry) => {
              if (entry.type === "separator") {
                return html`<div class="day-separator"><span class="day-label">${entry.label}</span></div>`;
              }
              return html`
                <div class="activity-item">
                  ${entry.completedBy
                    ? this._renderAvatar(entry.completedBy)
                    : html`<span class="avatar avatar-fallback">?</span>`}
                  <div class="activity-text">
                    <span class="activity-person">${this._getPersonName(entry.completedBy) || "Unknown"}</span>
                    <span class="activity-verb">completed</span>
                    <span class="activity-task">${entry.taskName}</span>
                    ${this._config.show_task_type && entry.subentryType === "maintenance"
                      ? html`<span class="type-badge maintenance-type"><ha-icon icon="mdi:wrench" class="type-badge-icon"></ha-icon></span>`
                      : ""}
                  </div>
                  <span class="activity-time">${this._formatRelativeTime(entry.completedAt)}</span>
                </div>
              `;
            })}
          </div>
        </ha-card>
      `;
    }

    static get styles() {
      return css`
        :host {
          --task-card-spacing: 12px;
        }

        ha-card {
          padding: 0;
          overflow: hidden;
        }

        .card-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 16px 16px 12px;
        }

        .header-icon {
          --mdc-icon-size: 22px;
          color: var(--primary-color);
        }

        .header-title {
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color);
          flex: 1;
        }

        .item-count {
          font-size: 12px;
          font-weight: 600;
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 12%, transparent);
          border-radius: 10px;
          padding: 2px 8px;
          min-width: 20px;
          text-align: center;
        }

        .activity-list {
          padding: 0 var(--task-card-spacing) var(--task-card-spacing);
        }

        .day-separator {
          padding: 8px 4px 4px;
        }

        .day-separator:first-child {
          padding-top: 0;
        }

        .day-label {
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--secondary-text-color);
          opacity: 0.7;
        }

        .activity-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 4px;
          border-radius: 8px;
          transition: background 0.15s ease;
        }

        .activity-item:hover {
          background: color-mix(in srgb, var(--primary-text-color) 4%, transparent);
        }

        .avatar {
          width: 24px;
          height: 24px;
          border-radius: 50%;
          object-fit: cover;
          flex-shrink: 0;
        }

        .avatar-fallback {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
          color: var(--primary-color);
          font-size: 11px;
          font-weight: 600;
        }

        .activity-text {
          flex: 1;
          font-size: 12px;
          color: var(--secondary-text-color);
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .activity-person {
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .activity-verb {
          margin: 0 3px;
        }

        .activity-task {
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .type-badge {
          display: inline-flex;
          align-items: center;
          vertical-align: middle;
          margin-left: 4px;
          padding: 1px 4px;
          border-radius: 4px;
          font-size: 10px;
        }

        .maintenance-type {
          background: color-mix(in srgb, var(--info-color, #2196f3) 12%, transparent);
          color: var(--info-color, #2196f3);
        }

        .type-badge-icon {
          --mdc-icon-size: 12px;
        }

        .activity-time {
          font-size: 11px;
          color: var(--secondary-text-color);
          opacity: 0.7;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          padding: 32px 16px;
          color: var(--secondary-text-color);
        }

        .empty-icon {
          --mdc-icon-size: 48px;
          opacity: 0.25;
          margin-bottom: 4px;
          color: var(--secondary-text-color);
        }

        .empty-title {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .empty-subtitle {
          font-size: 12px;
          opacity: 0.7;
        }

        .loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          padding: 32px 16px;
          color: var(--secondary-text-color);
          font-size: 13px;
        }

        .loading-pulse {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--primary-color) 15%, transparent);
          animation: pulse 1.2s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { transform: scale(0.9); opacity: 0.5; }
          50% { transform: scale(1.1); opacity: 1; }
        }
      `;
    }
  }

  customElements.define("task-activity-card", TaskActivityCard);

  window.customCards.push({
    type: "task-activity-card",
    name: "Task Activity Card",
    description: "Recent task completion activity feed",
    preview: true,
  });

  // ─────────────────────────────────────────────────────────
  // TaskActivityCardEditor
  // ─────────────────────────────────────────────────────────

  class TaskActivityCardEditor extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
      };
    }

    setConfig(config) {
      this._config = {
        max_items: 15,
        show_task_type: true,
        ...config,
      };
    }

    _fireChanged() {
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        })
      );
    }

    _schemaChanged(ev) {
      this._config = { ...this._config, ...ev.detail.value };
      this._fireChanged();
    }

    render() {
      if (!this._config) return html``;

      const schema = [
        { name: "areas", selector: { area: { multiple: true } } },
        { name: "title", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
        {
          name: "max_items",
          selector: { number: { min: 1, max: 100, mode: "box" } },
        },
        {
          name: "show_task_type",
          selector: { boolean: {} },
        },
      ];

      return html`
        <ha-form
          .hass=${this.hass}
          .data=${this._config}
          .schema=${schema}
          .computeLabel=${(s) => {
            const labels = {
              areas: "Areas",
              title: "Title (optional)",
              icon: "Icon (optional)",
              max_items: "Maximum items",
              show_task_type: "Show task/maintenance badge",
            };
            return labels[s.name] || s.name;
          }}
          @value-changed=${this._schemaChanged}
        ></ha-form>
      `;
    }

    static get styles() {
      return css`
        ha-form {
          display: block;
          padding: 16px;
        }
      `;
    }
  }

  customElements.define("task-activity-card-editor", TaskActivityCardEditor);

  // ─────────────────────────────────────────────────────────
  // TaskRankingCard — leaderboard / user rankings
  // ─────────────────────────────────────────────────────────

  class TaskRankingCard extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
        _period: { type: String },
      };
    }

    constructor() {
      super();
      this._period = "all_time";
    }

    setConfig(config) {
      if (!config.area && !config.areas) {
        throw new Error("Please define 'area' or 'areas'");
      }
      this._config = {
        title: "Task Champions",
        icon: "mdi:trophy",
        period: "all_time",
        show_streak: true,
        show_bar: true,
        ...config,
      };
      this._period = this._config.period;
    }

    set hass(hass) {
      this._hass = hass;
      this.requestUpdate();
    }

    get hass() {
      return this._hass;
    }

    getCardSize() {
      return 4;
    }

    static getConfigElement() {
      return document.createElement("task-ranking-card-editor");
    }

    static getStubConfig() {
      return { area: "", period: "all_time" };
    }

    _getAreaList() {
      return this._config.areas
        || (this._config.area ? (Array.isArray(this._config.area) ? this._config.area : [this._config.area]) : null);
    }

    _getTaskEntities() {
      if (!this.hass) return [];
      const areaList = this._getAreaList();
      if (!areaList) return [];
      return Object.entries(this.hass.states)
        .filter(([eid, state]) => {
          if (!eid.startsWith("sensor.")) return false;
          const attrs = state.attributes;
          return (
            areaList.includes(attrs.area_id) &&
            attrs.interval_days !== undefined &&
            !eid.endsWith("_history")
          );
        })
        .map(([eid, state]) => ({ entityId: eid, state }));
    }

    _getPersonName(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state ? state.attributes.friendly_name || state.state : personEntityId.replace("person.", "").replace(/_/g, " ");
    }

    _getPersonAvatar(personEntityId) {
      if (!personEntityId || !this.hass) return null;
      const state = this.hass.states[personEntityId];
      return state?.attributes?.entity_picture || null;
    }

    _renderAvatar(personEntityId, large) {
      const avatar = this._getPersonAvatar(personEntityId);
      const name = this._getPersonName(personEntityId);
      const cls = large ? "avatar avatar-large" : "avatar";
      if (avatar) {
        return html`<img class="${cls}" src="${avatar}" alt="${name}" />`;
      }
      const initial = name ? name.charAt(0).toUpperCase() : "?";
      return html`<span class="${cls} avatar-fallback">${initial}</span>`;
    }

    _setPeriod(period) {
      this._period = period;
    }

    _getPeriodCutoff() {
      const now = new Date();
      if (this._period === "week") {
        return new Date(now.getTime() - 7 * 86400000);
      }
      if (this._period === "month") {
        return new Date(now.getTime() - 30 * 86400000);
      }
      return null;
    }

    _getRankings() {
      const tasks = this._getTaskEntities();
      const cutoff = this._getPeriodCutoff();
      const counts = {};

      for (const { state } of tasks) {
        const completions = state.attributes.recent_completions;
        if (!completions) continue;
        for (const entry of completions) {
          if (cutoff && new Date(entry.completed_at) < cutoff) continue;
          const person = entry.completed_by || "__unknown__";
          counts[person] = (counts[person] || 0) + 1;
        }
      }

      return Object.entries(counts)
        .map(([personId, count]) => ({ personId, count }))
        .sort((a, b) => b.count - a.count);
    }

    _getStreak(personId) {
      const tasks = this._getTaskEntities();
      const allDates = new Set();

      for (const { state } of tasks) {
        const completions = state.attributes.recent_completions;
        if (!completions) continue;
        for (const entry of completions) {
          if (entry.completed_by !== personId) continue;
          const d = new Date(entry.completed_at);
          allDates.add(`${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`);
        }
      }

      if (allDates.size === 0) return 0;

      let streak = 0;
      const now = new Date();
      let check = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      while (true) {
        const key = `${check.getFullYear()}-${check.getMonth()}-${check.getDate()}`;
        if (allDates.has(key)) {
          streak++;
          check = new Date(check.getTime() - 86400000);
        } else if (streak === 0) {
          check = new Date(check.getTime() - 86400000);
          const prevKey = `${check.getFullYear()}-${check.getMonth()}-${check.getDate()}`;
          if (allDates.has(prevKey)) {
            streak++;
            check = new Date(check.getTime() - 86400000);
          } else {
            break;
          }
        } else {
          break;
        }
      }

      return streak;
    }

    _getRankAccent(rank) {
      if (rank === 1) return "#FFD700";
      if (rank === 2) return "#C0C0C0";
      if (rank === 3) return "#CD7F32";
      return null;
    }

    _getRankIcon(rank) {
      if (rank === 1) return "mdi:crown";
      if (rank === 2) return "mdi:medal";
      if (rank === 3) return "mdi:medal-outline";
      return null;
    }

    render() {
      if (!this.hass || !this._config) {
        return html`<ha-card>
          <div class="loading">
            <div class="loading-pulse"></div>
            <span>Loading rankings…</span>
          </div>
        </ha-card>`;
      }

      const rankings = this._getRankings();
      const maxCount = rankings.length > 0 ? rankings[0].count : 1;
      const title = this._config.title || "Task Champions";
      const periodLabels = { all_time: "All Time", month: "Month", week: "Week" };

      if (rankings.length === 0) {
        return html`
          <ha-card>
            <div class="card-header">
              <ha-icon icon=${this._config.icon || "mdi:trophy"} class="header-icon"></ha-icon>
              <span class="header-title">${title}</span>
            </div>
            <div class="period-bar">
              ${["all_time", "month", "week"].map(
                (p) => html`
                  <button class="period-chip ${this._period === p ? "active" : ""}" @click=${() => this._setPeriod(p)}>
                    ${periodLabels[p]}
                  </button>
                `
              )}
            </div>
            <div class="empty-state">
              <ha-icon icon="mdi:trophy-outline" class="empty-icon"></ha-icon>
              <span class="empty-title">No completions yet</span>
              <span class="empty-subtitle">Who will be first?</span>
            </div>
          </ha-card>
        `;
      }

      return html`
        <ha-card>
          <div class="card-header">
            <ha-icon icon=${this._config.icon || "mdi:trophy"} class="header-icon"></ha-icon>
            <span class="header-title">${title}</span>
          </div>
          <div class="period-bar">
            ${["all_time", "month", "week"].map(
              (p) => html`
                <button class="period-chip ${this._period === p ? "active" : ""}" @click=${() => this._setPeriod(p)}>
                  ${periodLabels[p]}
                </button>
              `
            )}
          </div>
          <div class="ranking-list">
            ${rankings.map((entry, idx) => {
              const rank = idx + 1;
              const accent = this._getRankAccent(rank);
              const rankIcon = this._getRankIcon(rank);
              const isTop3 = rank <= 3;
              const barWidth = this._config.show_bar ? Math.max(8, (entry.count / maxCount) * 100) : 0;
              const streak = this._config.show_streak ? this._getStreak(entry.personId) : 0;

              return html`
                <div class="rank-row ${isTop3 ? "top-3" : ""}" style=${accent ? `--rank-accent: ${accent}` : ""}>
                  ${this._config.show_bar ? html`
                    <div class="rank-bar" style="width: ${barWidth}%"></div>
                  ` : ""}
                  <div class="rank-content">
                    <span class="rank-number ${isTop3 ? "rank-top" : ""}">
                      ${rankIcon
                        ? html`<ha-icon icon=${rankIcon} class="rank-icon" style="color: ${accent}"></ha-icon>`
                        : html`${rank}`}
                    </span>
                    ${this._renderAvatar(entry.personId, isTop3)}
                    <div class="rank-info">
                      <span class="rank-name">${this._getPersonName(entry.personId) || "Unknown"}</span>
                      ${streak > 0 ? html`
                        <span class="streak-badge">
                          <ha-icon icon="mdi:fire" class="streak-icon"></ha-icon>${streak}d
                        </span>
                      ` : ""}
                    </div>
                    <span class="rank-count ${isTop3 ? "count-top" : ""}">${entry.count}</span>
                  </div>
                </div>
              `;
            })}
          </div>
        </ha-card>
      `;
    }

    static get styles() {
      return css`
        :host {
          --task-card-spacing: 12px;
        }

        ha-card {
          padding: 0;
          overflow: hidden;
        }

        .card-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 16px 16px 8px;
        }

        .header-icon {
          --mdc-icon-size: 22px;
          color: var(--primary-color);
        }

        .header-title {
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color);
          flex: 1;
        }

        /* ── Period chips ── */

        .period-bar {
          display: flex;
          gap: 6px;
          padding: 0 16px 10px;
        }

        .period-chip {
          border: none;
          border-radius: 12px;
          padding: 4px 10px;
          font-size: 11px;
          font-weight: 500;
          font-family: inherit;
          cursor: pointer;
          transition: background 0.2s ease, color 0.2s ease, transform 0.1s ease;
          background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
          color: var(--secondary-text-color);
          height: 24px;
          display: inline-flex;
          align-items: center;
        }

        .period-chip:hover {
          background: color-mix(in srgb, var(--primary-color) 15%, transparent);
          color: var(--primary-color);
        }

        .period-chip.active {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }

        .period-chip:active {
          transform: scale(0.95);
        }

        /* ── Ranking list ── */

        .ranking-list {
          display: flex;
          flex-direction: column;
          gap: 2px;
          padding: 0 var(--task-card-spacing) var(--task-card-spacing);
        }

        .rank-row {
          position: relative;
          border-radius: 10px;
          overflow: hidden;
          transition: transform 0.15s ease;
        }

        .rank-row:hover {
          transform: translateX(2px);
        }

        .rank-bar {
          position: absolute;
          top: 0;
          left: 0;
          bottom: 0;
          background: color-mix(in srgb, var(--rank-accent, var(--primary-color)) 10%, transparent);
          border-radius: 10px;
          transition: width 0.4s ease;
        }

        .rank-content {
          position: relative;
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 10px;
          z-index: 1;
        }

        .top-3 .rank-content {
          padding: 10px;
        }

        .rank-number {
          width: 24px;
          text-align: center;
          font-size: 13px;
          font-weight: 600;
          color: var(--secondary-text-color);
          flex-shrink: 0;
        }

        .rank-top {
          font-size: 0;
        }

        .rank-icon {
          --mdc-icon-size: 20px;
        }

        .top-3 .rank-icon {
          --mdc-icon-size: 22px;
        }

        .avatar {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          object-fit: cover;
          flex-shrink: 0;
        }

        .avatar-large {
          width: 34px;
          height: 34px;
        }

        .avatar-fallback {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
          color: var(--primary-color);
          font-size: 12px;
          font-weight: 600;
        }

        .avatar-large.avatar-fallback {
          font-size: 14px;
        }

        .rank-info {
          flex: 1;
          min-width: 0;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .rank-name {
          font-size: 13px;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .top-3 .rank-name {
          font-size: 14px;
          font-weight: 600;
        }

        .streak-badge {
          display: inline-flex;
          align-items: center;
          gap: 2px;
          font-size: 10px;
          font-weight: 600;
          color: var(--warning-color, #ff9800);
          background: color-mix(in srgb, var(--warning-color, #ff9800) 12%, transparent);
          border-radius: 8px;
          padding: 1px 5px;
          flex-shrink: 0;
        }

        .streak-icon {
          --mdc-icon-size: 12px;
          color: var(--warning-color, #ff9800);
        }

        .rank-count {
          font-size: 15px;
          font-weight: 700;
          color: var(--primary-text-color);
          flex-shrink: 0;
          min-width: 28px;
          text-align: right;
        }

        .count-top {
          font-size: 18px;
          color: var(--rank-accent, var(--primary-color));
        }

        /* ── States ── */

        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          padding: 32px 16px;
          color: var(--secondary-text-color);
        }

        .empty-icon {
          --mdc-icon-size: 48px;
          opacity: 0.25;
          margin-bottom: 4px;
          color: var(--secondary-text-color);
        }

        .empty-title {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color);
        }

        .empty-subtitle {
          font-size: 12px;
          opacity: 0.7;
        }

        .loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          padding: 32px 16px;
          color: var(--secondary-text-color);
          font-size: 13px;
        }

        .loading-pulse {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--primary-color) 15%, transparent);
          animation: pulse 1.2s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { transform: scale(0.9); opacity: 0.5; }
          50% { transform: scale(1.1); opacity: 1; }
        }
      `;
    }
  }

  customElements.define("task-ranking-card", TaskRankingCard);

  window.customCards.push({
    type: "task-ranking-card",
    name: "Task Ranking Card",
    description: "Leaderboard showing who completes the most tasks",
    preview: true,
  });

  // ─────────────────────────────────────────────────────────
  // TaskRankingCardEditor
  // ─────────────────────────────────────────────────────────

  class TaskRankingCardEditor extends LitElement {
    static get properties() {
      return {
        hass: { type: Object },
        _config: { type: Object },
      };
    }

    setConfig(config) {
      this._config = {
        title: "Task Champions",
        icon: "mdi:trophy",
        period: "all_time",
        show_streak: true,
        show_bar: true,
        ...config,
      };
    }

    _fireChanged() {
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        })
      );
    }

    _schemaChanged(ev) {
      this._config = { ...this._config, ...ev.detail.value };
      this._fireChanged();
    }

    render() {
      if (!this._config) return html``;

      const schema = [
        { name: "areas", selector: { area: { multiple: true } } },
        { name: "title", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
        {
          name: "period",
          selector: {
            select: {
              options: [
                { value: "all_time", label: "All Time" },
                { value: "month", label: "Last 30 Days" },
                { value: "week", label: "Last 7 Days" },
              ],
              mode: "dropdown",
            },
          },
        },
        {
          name: "show_streak",
          selector: { boolean: {} },
        },
        {
          name: "show_bar",
          selector: { boolean: {} },
        },
      ];

      return html`
        <ha-form
          .hass=${this.hass}
          .data=${this._config}
          .schema=${schema}
          .computeLabel=${(s) => {
            const labels = {
              areas: "Areas",
              title: "Title (optional)",
              icon: "Icon (optional)",
              period: "Default period",
              show_streak: "Show streak badges",
              show_bar: "Show visual bar",
            };
            return labels[s.name] || s.name;
          }}
          @value-changed=${this._schemaChanged}
        ></ha-form>
      `;
    }

    static get styles() {
      return css`
        ha-form {
          display: block;
          padding: 16px;
        }
      `;
    }
  }

  customElements.define("task-ranking-card-editor", TaskRankingCardEditor);
})();
