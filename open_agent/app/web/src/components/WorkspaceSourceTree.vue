<template>
  <div class="workspace-source-tree" :class="{ nested: level > 0 }">
    <article
      v-for="source in sources"
      :key="source.path"
      class="source-tree-item"
      :class="{
        nested: level > 0,
        selected: selectionState(source) === 'full',
        partial: selectionState(source) === 'partial',
      }"
    >
      <div class="source-tree-row" @click="onRowClick(source)">
        <button
          v-if="source.type === 'directory'"
          class="source-expand"
          :class="{ expanded: expandedPathSet.has(source.path) }"
          type="button"
          @click.stop="$emit('toggle-expanded', source.path)"
          :aria-label="expandedPathSet.has(source.path) ? 'Collapse folder' : 'Expand folder'"
          title="Expand"
        >
          ^
        </button>
        <span v-else class="source-expand placeholder"></span>

        <label class="source-check" @click.stop>
          <input
            type="checkbox"
            :checked="selectionState(source) === 'full'"
            :indeterminate="selectionState(source) === 'partial'"
            :aria-checked="selectionState(source) === 'partial' ? 'mixed' : selectionState(source) === 'full' ? 'true' : 'false'"
            @change="$emit('toggle-select', source.path)"
          />
          <span></span>
        </label>

        <span class="source-type-icon">
          <svg v-if="source.type === 'directory'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
          </svg>
          <svg v-else-if="source.type === 'web'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M2 12h20"/>
            <path d="M12 2a15 15 0 0 1 0 20"/>
            <path d="M12 2a15 15 0 0 0 0 20"/>
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <path d="M14 2v6h6"/>
          </svg>
        </span>

        <div class="source-tree-copy">
          <h4>{{ source.name }}</h4>
          <p>{{ source.type === 'directory' ? directorySummary(source) : source.path }}</p>
        </div>

        <div class="source-actions">
          <button
            class="source-action"
            type="button"
            @click.stop="$emit('open-location', source)"
            title="Open location"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 3h7v7"/>
              <path d="M10 14 21 3"/>
              <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>
            </svg>
          </button>
          <button
            v-if="level === 0"
            class="source-action source-remove"
            type="button"
            @click.stop="$emit('remove-source', source.id || source.path)"
            title="Remove"
          >
            x
          </button>
        </div>
      </div>

      <WorkspaceSourceTree
        v-if="source.type === 'directory' && expandedPathSet.has(source.path) && source.children?.length"
        :sources="source.children"
        :selected-paths="selectedPaths"
        :expanded-paths="expandedPaths"
        :level="level + 1"
        @toggle-select="$emit('toggle-select', $event)"
        @toggle-expanded="$emit('toggle-expanded', $event)"
        @remove-source="$emit('remove-source', $event)"
        @open-location="$emit('open-location', $event)"
      />
    </article>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceSourceNode } from '@/types'

const props = withDefaults(defineProps<{
  sources: WorkspaceSourceNode[]
  selectedPaths: string[]
  expandedPaths: string[]
  level?: number
}>(), {
  level: 0,
})

const emit = defineEmits<{
  (event: 'toggle-select', path: string): void
  (event: 'toggle-expanded', path: string): void
  (event: 'remove-source', idOrPath: string): void
  (event: 'open-location', source: WorkspaceSourceNode): void
}>()

const selectedPathSet = computed(() => new Set(props.selectedPaths))
const expandedPathSet = computed(() => new Set(props.expandedPaths))
type SourceSelectionState = 'none' | 'partial' | 'full'

function collectPaths(source: WorkspaceSourceNode): string[] {
  const childPaths = (source.children || []).flatMap(collectPaths)
  return [source.path, ...childPaths]
}

function selectionState(source: WorkspaceSourceNode): SourceSelectionState {
  const paths = collectPaths(source)
  const selectedCount = paths.filter(path => selectedPathSet.value.has(path)).length
  if (selectedCount === 0) return 'none'
  if (selectedCount === paths.length) return 'full'
  return 'partial'
}

function directorySummary(source: WorkspaceSourceNode): string {
  const count = source.children_count ?? source.children?.length ?? 0
  return `${source.path}${count ? ` · ${count} items` : ''}`
}

function onRowClick(source: WorkspaceSourceNode): void {
  if (source.type === 'directory') {
    emit('toggle-expanded', source.path)
  }
}
</script>

<style scoped>
.workspace-source-tree {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  overflow-anchor: none;
}

.workspace-source-tree.nested {
  gap: 6px;
  margin: 6px 0 0 10px;
  padding-left: 8px;
  border-left: 1px solid var(--border-color);
}

.source-tree-item {
  min-width: 0;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--glass-bg-strong);
  overflow: hidden;
}

.source-tree-item.nested {
  border-radius: 12px;
  background: color-mix(in srgb, var(--glass-bg-strong) 88%, transparent);
}

.source-tree-item.selected {
  border-color: color-mix(in srgb, var(--primary-color) 48%, var(--border-color));
  background: color-mix(in srgb, var(--glass-bg-strong) 86%, rgba(47, 110, 244, 0.1));
}

.source-tree-item.partial {
  border-color: color-mix(in srgb, var(--primary-color) 28%, var(--border-color));
  background: color-mix(in srgb, var(--glass-bg-strong) 92%, rgba(47, 110, 244, 0.08));
}

.source-tree-row {
  display: grid;
  grid-template-columns: 22px 22px 34px minmax(0, 1fr) auto;
  align-items: start;
  gap: 7px;
  min-width: 0;
  min-height: 58px;
  padding: 8px;
  cursor: pointer;
}

.source-expand,
.source-check,
.source-type-icon,
.source-actions {
  margin-top: 2px;
}

.source-expand {
  width: 22px;
  height: 22px;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: var(--glass-bg);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  box-shadow: inset 0 1px 0 var(--glass-border);
  transform: rotate(90deg);
  transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.source-expand.expanded {
  border-color: color-mix(in srgb, var(--primary-color) 42%, var(--border-color));
  background: color-mix(in srgb, var(--primary-color) 10%, var(--glass-bg));
  color: var(--primary-color);
  transform: rotate(180deg);
}

.source-expand:hover {
  border-color: color-mix(in srgb, var(--primary-color) 36%, var(--border-color));
  background: var(--glass-bg-strong);
  color: var(--text-primary);
}

.source-expand.placeholder {
  border-color: transparent;
  background: transparent;
  box-shadow: none;
  pointer-events: none;
}

.source-check {
  position: relative;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.source-check input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: pointer;
}

.source-check span {
  width: 16px;
  height: 16px;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  background: var(--glass-bg);
  box-shadow: inset 0 1px 0 var(--glass-border);
  transition: all 0.18s ease;
}

.source-check input:checked + span {
  border-color: var(--primary-color);
  background: var(--primary-color);
  box-shadow: inset 0 0 0 3px var(--glass-bg-strong);
}

.source-check input:indeterminate + span {
  position: relative;
  border-color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 18%, var(--glass-bg));
}

.source-check input:indeterminate + span::after {
  position: absolute;
  top: 50%;
  left: 3px;
  right: 3px;
  height: 2px;
  border-radius: 999px;
  background: var(--primary-color);
  content: '';
  transform: translateY(-50%);
}

.source-type-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(47, 110, 244, 0.1);
  color: var(--primary-color);
}

.source-type-icon svg {
  width: 17px;
  height: 17px;
}

.source-tree-copy {
  min-width: 0;
}

.source-tree-copy h4 {
  margin: 0 0 3px;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-tree-copy p {
  margin: 0;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  min-width: 56px;
}

.source-action {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.source-action:hover {
  border-color: var(--border-color);
  background: var(--hover-bg);
  color: var(--text-primary);
}

.source-action svg {
  width: 15px;
  height: 15px;
}
</style>
