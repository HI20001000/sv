<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  deleteInputDocument,
  getEpisode,
  getHealth,
  getInputDocuments,
  getOutputProject,
  getOutputProjects,
  getPrompt,
  getPrompts,
  getStoryboard,
  getWorkflowJob,
  runWorkflow,
  sendChatMessage,
  updatePrompt,
  uploadInputDocument,
} from './api'

const health = ref(null)
const documents = ref([])
const projects = ref([])
const projectBundle = ref(null)
const episodeDetail = ref(null)
const storyboardDetail = ref(null)

const selectedDocument = ref('')
const selectedProject = ref('')
const selectedEpisodeNo = ref(null)
const selectedStoryboardNo = ref(null)
const activeOutputTab = ref('story')
const activeWorkspaceView = ref('workspace')

const promptWorkflow = ref([])
const selectedPromptKey = ref('')
const promptDetail = ref(null)
const promptDraft = ref('')
const promptOriginal = ref('')
const promptStatus = ref('')

const chatInput = ref('')
const chatStream = ref(null)
const fileInput = ref(null)
const notice = ref('')
const workflowPollers = new Map()
const busy = ref({
  chat: false,
  upload: false,
  workflow: false,
  project: false,
  episode: false,
  storyboard: false,
  prompts: false,
  promptDetail: false,
  promptSave: false,
})
const chatMessages = ref([
  {
    role: 'system',
    type: 'system',
    content: 'Workspace ready. Use chat or /docs to start.',
  },
])

const projectSummary = computed(() => {
  return projects.value.find((item) => item.name === selectedProject.value) || null
})
const storyBible = computed(() => projectBundle.value?.story_bible || null)
const storyCharacters = computed(() => storyBible.value?.characters || [])
const storyProps = computed(() => storyBible.value?.props || [])
const storyBackground = computed(() => storyBible.value?.background || {})
const storyBackgroundRows = computed(() => {
  const background = storyBackground.value || {}

  return [
    { label: 'Era', value: formatInlineValue(background.era) },
    { label: 'Locations', value: formatInlineValue(background.locations) },
    { label: 'Social Context', value: formatInlineValue(background.social_context) },
    { label: 'World Rules', value: formatInlineValue(background.world_rules) },
  ].filter((item) => item.value !== '--')
})
const episodeItems = computed(() => projectBundle.value?.episodes_index?.episodes || [])
const storyboardItems = computed(() => projectBundle.value?.storyboards_index?.episodes || [])
const selectedPromptStep = computed(() => {
  return promptWorkflow.value.find((item) => item.key === selectedPromptKey.value) || null
})
const hasPromptChanges = computed(() => promptDraft.value !== promptOriginal.value)
const workspaceGridClass = computed(() => {
  return activeWorkspaceView.value === 'prompts' ? 'workspace-grid-prompts' : ''
})
const apiStatusClass = computed(() => {
  if (!health.value) return 'status-connecting'
  return health.value.status === 'ok' ? 'status-ok' : 'status-error'
})
const llmStatusClass = computed(() => {
  if (!health.value) return 'status-connecting'
  return health.value.has_llm_env ? 'status-ok' : 'status-error'
})

function formatFileSize(size) {
  if (!size && size !== 0) return '--'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value) {
  if (!value) return 'Unknown'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function prettyJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

function formatRate(value) {
  if (typeof value !== 'number') return '--'
  return `${(value * 100).toFixed(1)}%`
}

function formatDuration(value) {
  if (typeof value !== 'number') return '--'
  return `${value.toFixed(1)}s`
}

function joinList(value) {
  if (!Array.isArray(value) || !value.length) return '--'
  return value.join(' / ')
}

function formatInlineValue(value) {
  if (Array.isArray(value)) {
    return value.length ? value.join(' / ') : '--'
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value)
  }
  return value || '--'
}

function formatWorkflowMessage(payload) {
  const result = payload?.result || {}
  return [
    payload?.message || 'Workflow completed.',
    `Project: ${result.project_dir || '--'}`,
    `Episodes: ${result.generated_episode_count || 0}`,
    `Storyboards: ${result.generated_storyboard_count || 0}`,
    `Elapsed: ${result.total_elapsed_seconds ? `${result.total_elapsed_seconds.toFixed(2)}s` : '--'}`,
  ].join('\n')
}

function pushMessage(role, content, type = role) {
  chatMessages.value.push({ role, content, type })
}

async function scrollChatToBottom() {
  await nextTick()
  if (!chatStream.value) return
  chatStream.value.scrollTop = chatStream.value.scrollHeight
}

function clearPromptEditor() {
  selectedPromptKey.value = ''
  promptDetail.value = null
  promptDraft.value = ''
  promptOriginal.value = ''
}

async function refreshHealth() {
  health.value = await getHealth()
}

async function refreshDocuments() {
  const data = await getInputDocuments()
  documents.value = data.items || []

  if (!selectedDocument.value && documents.value.length) {
    selectedDocument.value = documents.value[0].name
  }

  if (
    selectedDocument.value &&
    !documents.value.some((item) => item.name === selectedDocument.value)
  ) {
    selectedDocument.value = documents.value[0]?.name || ''
  }
}

async function refreshProjects() {
  const data = await getOutputProjects()
  projects.value = data.items || []

  if (!selectedProject.value && projects.value.length) {
    await openProject(projects.value[0].name)
    return
  }

  if (
    selectedProject.value &&
    !projects.value.some((item) => item.name === selectedProject.value)
  ) {
    const fallback = projects.value[0]?.name || ''
    if (fallback) {
      await openProject(fallback)
      return
    }
    selectedProject.value = ''
    projectBundle.value = null
    episodeDetail.value = null
    storyboardDetail.value = null
  }
}

function stopWorkflowPolling(jobId) {
  const timer = workflowPollers.get(jobId)
  if (timer) {
    window.clearInterval(timer)
    workflowPollers.delete(jobId)
  }
}

async function trackWorkflowJob(jobId) {
  let seenLogCount = 0

  const poll = async () => {
    try {
      const job = await getWorkflowJob(jobId)
      const logs = Array.isArray(job.logs) ? job.logs : []
      const newLogs = logs.slice(seenLogCount)

      newLogs.forEach((log) => {
        pushMessage('assistant', log, 'workflow')
      })
      seenLogCount = logs.length

      if (job.status === 'completed') {
        stopWorkflowPolling(jobId)
        pushMessage(
          'assistant',
          formatWorkflowMessage({
            message: `Completed /docs workflow for ${job.filename}`,
            result: job.result,
          }),
          'workflow',
        )
        busy.value.workflow = false
        await Promise.all([refreshProjects(), refreshHealth()])
        if (job.result?.project_dir) {
          await openProject(job.result.project_dir)
          activeOutputTab.value = 'story'
        }
      }

      if (job.status === 'failed') {
        stopWorkflowPolling(jobId)
        pushMessage('assistant', `Workflow failed: ${job.error || 'Unknown error'}`, 'error')
        busy.value.workflow = false
      }
    } catch (error) {
      stopWorkflowPolling(jobId)
      busy.value.workflow = false
      notice.value = error.message
      pushMessage('assistant', `Workflow polling failed: ${error.message}`, 'error')
    }
  }

  await poll()
  if (!workflowPollers.has(jobId)) {
    const timer = window.setInterval(poll, 1200)
    workflowPollers.set(jobId, timer)
  }
}

async function openProject(projectName) {
  if (!projectName) return

  busy.value.project = true
  try {
    const data = await getOutputProject(projectName)
    selectedProject.value = projectName
    projectBundle.value = data

    const firstEpisode = data.episodes_index?.episodes?.[0]?.episode_no
    const firstStoryboard = data.storyboards_index?.episodes?.[0]?.episode_no

    if (firstEpisode) {
      await openEpisode(firstEpisode, projectName)
    } else {
      episodeDetail.value = null
      selectedEpisodeNo.value = null
    }

    if (firstStoryboard) {
      await openStoryboard(firstStoryboard, projectName)
    } else {
      storyboardDetail.value = null
      selectedStoryboardNo.value = null
    }
  } finally {
    busy.value.project = false
  }
}

async function openEpisode(episodeNo, projectName = selectedProject.value) {
  if (!projectName || !episodeNo) return
  busy.value.episode = true
  try {
    const data = await getEpisode(projectName, episodeNo)
    episodeDetail.value = data.data
    selectedEpisodeNo.value = episodeNo
  } finally {
    busy.value.episode = false
  }
}

async function openStoryboard(episodeNo, projectName = selectedProject.value) {
  if (!projectName || !episodeNo) return
  busy.value.storyboard = true
  try {
    const data = await getStoryboard(projectName, episodeNo)
    storyboardDetail.value = data.data
    selectedStoryboardNo.value = episodeNo
  } finally {
    busy.value.storyboard = false
  }
}

async function refreshPromptWorkflow({ preserveSelection = true } = {}) {
  busy.value.prompts = true
  notice.value = ''

  try {
    const data = await getPrompts()
    promptWorkflow.value = data.items || []

    const nextKey =
      preserveSelection &&
      promptWorkflow.value.some((item) => item.key === selectedPromptKey.value && item.has_prompt)
        ? selectedPromptKey.value
        : data.default_prompt_key || promptWorkflow.value.find((item) => item.has_prompt)?.key || ''

    if (nextKey) {
      await openPromptStep(nextKey, { confirmDiscard: false })
    } else {
      clearPromptEditor()
    }
  } catch (error) {
    notice.value = error.message
    promptStatus.value = `Unable to load prompt workflow: ${error.message}`
  } finally {
    busy.value.prompts = false
  }
}

async function ensurePromptWorkflowLoaded() {
  if (!promptWorkflow.value.length) {
    await refreshPromptWorkflow({ preserveSelection: false })
    return
  }

  if (!selectedPromptKey.value) {
    const defaultKey = promptWorkflow.value.find((item) => item.has_prompt)?.key
    if (defaultKey) {
      await openPromptStep(defaultKey, { confirmDiscard: false })
    }
  }
}

async function openPromptStep(promptKey, { confirmDiscard = true } = {}) {
  const step = promptWorkflow.value.find((item) => item.key === promptKey)
  if (!step?.has_prompt) return

  if (
    confirmDiscard &&
    hasPromptChanges.value &&
    promptKey !== selectedPromptKey.value &&
    !window.confirm('You have unsaved prompt changes. Switching will discard them.')
  ) {
    return
  }

  busy.value.promptDetail = true
  notice.value = ''
  promptStatus.value = ''

  try {
    const data = await getPrompt(promptKey)
    selectedPromptKey.value = promptKey
    promptDetail.value = data
    promptDraft.value = data.content || ''
    promptOriginal.value = data.content || ''
  } catch (error) {
    notice.value = error.message
    promptStatus.value = `Unable to load prompt: ${error.message}`
  } finally {
    busy.value.promptDetail = false
  }
}

async function handleReloadPrompts() {
  if (
    hasPromptChanges.value &&
    !window.confirm('You have unsaved prompt changes. Reloading will discard them.')
  ) {
    return
  }

  await refreshPromptWorkflow({ preserveSelection: true })
  if (!notice.value) {
    promptStatus.value = 'Prompt workflow reloaded from disk.'
  }
}

function handleResetPromptDraft() {
  promptDraft.value = promptOriginal.value
  promptStatus.value = 'Unsaved changes were reset.'
}

async function handleSavePrompt() {
  if (!selectedPromptStep.value?.has_prompt || !selectedPromptKey.value) return

  busy.value.promptSave = true
  notice.value = ''
  promptStatus.value = ''

  try {
    const response = await updatePrompt(selectedPromptKey.value, promptDraft.value)
    promptOriginal.value = response.content || promptDraft.value
    promptDetail.value = {
      ...(promptDetail.value || {}),
      ...response,
      content: promptOriginal.value,
    }

    const workflowItem = promptWorkflow.value.find((item) => item.key === selectedPromptKey.value)
    if (workflowItem) {
      workflowItem.updated_at = response.updated_at
      workflowItem.prompt_exists = true
      workflowItem.file_name = response.file_name
      workflowItem.file_path = response.file_path
    }

    promptStatus.value = response.message || 'Prompt saved.'
  } catch (error) {
    notice.value = error.message
    promptStatus.value = `Save failed: ${error.message}`
  } finally {
    busy.value.promptSave = false
  }
}

async function toggleWorkspaceView(nextView) {
  if (nextView === activeWorkspaceView.value) return

  if (
    activeWorkspaceView.value === 'prompts' &&
    hasPromptChanges.value &&
    !window.confirm('You have unsaved prompt changes. Leaving will discard them.')
  ) {
    return
  }

  activeWorkspaceView.value = nextView
  promptStatus.value = ''

  if (nextView === 'prompts') {
    await ensurePromptWorkflowLoaded()
  }
}

async function bootstrap() {
  notice.value = ''
  try {
    await Promise.all([refreshHealth(), refreshDocuments(), refreshProjects()])
  } catch (error) {
    notice.value = error.message
  }
}

async function handleUpload(event) {
  const [file] = event.target.files || []
  if (!file) return

  busy.value.upload = true
  notice.value = ''

  try {
    const response = await uploadInputDocument(file)
    pushMessage('system', response.message, 'system')
    await Promise.all([refreshDocuments(), refreshHealth()])
  } catch (error) {
    notice.value = error.message
  } finally {
    busy.value.upload = false
    event.target.value = ''
  }
}

async function handleDelete(filename) {
  if (!window.confirm(`Delete ${filename}?`)) return

  notice.value = ''
  try {
    const response = await deleteInputDocument(filename)
    pushMessage('system', response.message, 'system')
    await Promise.all([refreshDocuments(), refreshHealth()])
  } catch (error) {
    notice.value = error.message
  }
}

async function handleRunWorkflow(filename = selectedDocument.value) {
  if (!filename) {
    notice.value = 'Select a file before running /docs.'
    return
  }

  busy.value.workflow = true
  notice.value = ''
  pushMessage('user', `/docs ${filename}`)

  try {
    const response = await runWorkflow(filename)
    pushMessage('assistant', response.message || `Started /docs workflow for ${filename}`, 'workflow')
    if (response.job?.job_id) {
      await trackWorkflowJob(response.job.job_id)
    } else {
      busy.value.workflow = false
    }
  } catch (error) {
    pushMessage('assistant', `Workflow failed: ${error.message}`, 'error')
    notice.value = error.message
    busy.value.workflow = false
  }
}

async function handleChatSubmit() {
  const message = chatInput.value.trim()
  if (!message || busy.value.chat) return

  busy.value.chat = true
  notice.value = ''
  pushMessage('user', message)
  chatInput.value = ''

  try {
    const response = await sendChatMessage(message)
    if (response.type === 'workflow_started' && response.job?.job_id) {
      pushMessage('assistant', response.message || `Started ${message}`, 'workflow')
      busy.value.workflow = true
      await trackWorkflowJob(response.job.job_id)
    } else {
      pushMessage('assistant', response.content, response.type || 'assistant')
      if (response.project_dir) {
        await Promise.all([refreshProjects(), refreshHealth()])
        await openProject(response.project_dir)
        activeOutputTab.value = 'story'
      }
    }
  } catch (error) {
    pushMessage('assistant', `Request failed: ${error.message}`, 'error')
    notice.value = error.message
  } finally {
    busy.value.chat = false
  }
}

onMounted(() => {
  bootstrap()
  scrollChatToBottom()
})

onBeforeUnmount(() => {
  workflowPollers.forEach((timer) => {
    window.clearInterval(timer)
  })
  workflowPollers.clear()
})

watch(
  () => chatMessages.value.length,
  () => {
    scrollChatToBottom()
  },
)

watch(
  () => busy.value.chat || busy.value.workflow,
  (isBusy, wasBusy) => {
    if (isBusy !== wasBusy) {
      scrollChatToBottom()
    }
  },
)
</script>

<template>
  <main class="workspace-shell">
    <header class="topbar">
      <div class="topbar-copy">
        <p class="panel-kicker">Short Video AI Console</p>

        <div class="topbar-actions">
          <button
            class="ghost-button"
            :class="{ 'toggle-active': activeWorkspaceView === 'workspace' }"
            type="button"
            title="Workspace"
            aria-label="Workspace"
            @click="toggleWorkspaceView('workspace')"
          >
            Workspace
          </button>
          <button
            class="ghost-button"
            :class="{ 'toggle-active': activeWorkspaceView === 'prompts' }"
            type="button"
            title="Prompt Lab"
            aria-label="Prompt Lab"
            @click="toggleWorkspaceView('prompts')"
          >
            Prompt Lab
          </button>
        </div>
      </div>

      <div class="status-strip">
        <div class="status-card">
          <span class="status-label">API</span>
          <span class="status-dot" :class="apiStatusClass"></span>
        </div>
        <div class="status-card">
          <span class="status-label">LLM</span>
          <span class="status-dot" :class="llmStatusClass"></span>
        </div>
        <div class="status-card">
          <span class="status-label">Inputs</span>
          <strong class="status-value">{{ documents.length }}</strong>
        </div>
        <div class="status-card">
          <span class="status-label">Outputs</span>
          <strong class="status-value">{{ projects.length }}</strong>
        </div>
      </div>
    </header>

    <p v-if="notice" class="notice">{{ notice }}</p>

    <section class="workspace-grid" :class="workspaceGridClass">
      <template v-if="activeWorkspaceView !== 'prompts'">
        <article class="panel panel-input">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">Input Documents</p>
            </div>
            <div class="panel-actions">
              <button
                class="ghost-button"
                type="button"
                :disabled="busy.upload"
                title="Upload"
                aria-label="Upload"
                @click="fileInput?.click()"
              >
                {{ busy.upload ? 'Uploading...' : 'Upload' }}
              </button>
              <button
                class="primary-button"
                type="button"
                :disabled="busy.workflow || !selectedDocument"
                title="Run /docs"
                aria-label="Run /docs"
                @click="handleRunWorkflow()"
              >
                {{ busy.workflow ? 'Running...' : 'Run /docs' }}
              </button>
              <input
                ref="fileInput"
                class="hidden-input"
                type="file"
                accept=".txt,.docx"
                @change="handleUpload"
              />
            </div>
          </div>

          <div v-if="documents.length" class="document-list">
            <article
              v-for="doc in documents"
              :key="doc.name"
              class="document-item"
              :class="{ active: selectedDocument === doc.name }"
            >
              <button class="document-item-select" type="button" @click="selectedDocument = doc.name">
                <div class="document-main">
                  <strong>{{ doc.name }}</strong>
                  <span>{{ doc.extension }} · {{ formatFileSize(doc.size) }}</span>
                </div>
              </button>
              <button
                class="danger-link"
                type="button"
                title="Delete"
                aria-label="Delete"
                @click.stop="handleDelete(doc.name)"
              >
                ✕
              </button>
            </article>
          </div>

          <div v-else class="empty-state">
            No files in `input_documents`. Upload a script and run `/docs`.
          </div>
        </article>
      </template>

      <article v-else class="panel panel-prompts">
        <div class="panel-head">
          <div>
            <p class="panel-kicker">Prompt Workflow</p>
            <h2>Agent Prompt Editor</h2>
          </div>
          <div class="panel-actions">
            <button
              class="ghost-button"
              type="button"
              title="Reload"
              aria-label="Reload"
              @click="handleReloadPrompts"
            >
              Reload
            </button>
            <button
              class="ghost-button"
              type="button"
              :disabled="!hasPromptChanges"
              title="Reset"
              aria-label="Reset"
              @click="handleResetPromptDraft"
            >
              Reset
            </button>
            <button
              class="primary-button"
              type="button"
              :disabled="busy.promptSave || !selectedPromptStep?.has_prompt || !hasPromptChanges"
              title="Save Prompt"
              aria-label="Save Prompt"
              @click="handleSavePrompt"
            >
              {{ busy.promptSave ? 'Saving...' : 'Save Prompt' }}
            </button>
          </div>
        </div>

        <div class="prompt-workspace">
          <aside class="prompt-workflow-list">
            <button
              v-for="step in promptWorkflow"
              :key="step.key"
              class="prompt-step-card"
              :class="{
                active: selectedPromptKey === step.key,
                disabled: !step.has_prompt,
              }"
              type="button"
              :disabled="!step.has_prompt"
              @click="openPromptStep(step.key)"
            >
              <span class="prompt-step-order">{{ String(step.order).padStart(2, '0') }}</span>
              <div class="prompt-step-main">
                <strong>{{ step.title }}</strong>
                <code>{{ step.file_name || 'No prompt file' }}</code>
              </div>
            </button>
          </aside>

          <section class="prompt-editor-panel">
            <div v-if="busy.prompts || busy.promptDetail" class="empty-state empty-state-compact">
              <div class="loading-stack">
                <span class="spinner-ring" aria-hidden="true"></span>
                <span>Loading prompt...</span>
              </div>
            </div>

            <template v-else-if="selectedPromptStep && promptDetail">
              <div class="prompt-editor-head">
                <div class="detail-head">
                  <h3>{{ selectedPromptStep.title }}</h3>
                  <div class="detail-meta-row">
                    <span class="muted">
                      Stage {{ selectedPromptStep.order }}/8 · {{ promptDetail.file_name }}
                    </span>
                    <span class="muted">
                      {{ hasPromptChanges ? 'Unsaved changes' : `Updated ${formatDate(selectedPromptStep.updated_at)}` }}
                    </span>
                  </div>
                </div>
              </div>

              <textarea v-model="promptDraft" class="prompt-editor-textarea" spellcheck="false" />
            </template>

            <div v-else class="empty-state empty-state-compact">
              No editable prompt is available. Reload the workflow first.
            </div>
          </section>
        </div>
      </article>

      <article class="panel panel-chat">
        <div class="panel-head">
          <div>
            <p class="panel-kicker">Chat Console</p>
          </div>
        </div>

        <div ref="chatStream" class="chat-stream">
          <article
            v-for="(message, index) in chatMessages"
            :key="`${message.role}-${index}`"
            class="message-card"
            :class="`message-${message.type}`"
          >
            <p class="message-role">{{ message.role }}</p>
            <pre class="message-content">{{ message.content }}</pre>
          </article>

          <article v-if="busy.chat || busy.workflow" class="message-card message-loading">
            <p class="message-role">system</p>
            <div class="loading-inline">
              <span class="spinner-dots" aria-hidden="true">
                <span></span>
                <span></span>
                <span></span>
              </span>
              <span>{{ busy.workflow ? 'Workflow running...' : 'Generating reply...' }}</span>
            </div>
          </article>
        </div>

        <form class="chat-composer" @submit.prevent="handleChatSubmit">
          <textarea
            v-model="chatInput"
            rows="4"
            placeholder="Type a message, or use /docs filename, /ping, /clear..."
          />
          <button class="primary-button" type="submit" :disabled="busy.chat" title="Send" aria-label="Send">
            {{ busy.chat ? '⏳' : '➤' }}
          </button>
        </form>
      </article>

      <template v-if="activeWorkspaceView !== 'prompts'">
        <article class="panel panel-output">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">Output Preview</p>
            </div>
            <select
              class="project-select"
              :value="selectedProject"
              @change="openProject($event.target.value)"
            >
              <option value="" disabled>Select Project</option>
              <option v-for="project in projects" :key="project.name" :value="project.name">
                {{ project.name }}
              </option>
            </select>
          </div>

          <div v-if="projectSummary" class="project-overview">
            <div class="overview-card">
              <span>Source File</span>
              <strong>{{ projectSummary.source_file || 'Unknown' }}</strong>
            </div>
            <div class="overview-card">
              <span>Created At</span>
              <strong>{{ formatDate(projectSummary.created_at) }}</strong>
            </div>
            <div class="overview-card">
              <span>Episodes</span>
              <strong>{{ projectSummary.generated_episode_count || 0 }}</strong>
            </div>
            <div class="overview-card">
              <span>Storyboards</span>
              <strong>{{ projectSummary.generated_storyboard_count || 0 }}</strong>
            </div>
          </div>

          <div class="tab-row">
            <button
              class="tab-button"
              :class="{ active: activeOutputTab === 'story' }"
              type="button"
              title="Story Bible"
              aria-label="Story Bible"
              @click="activeOutputTab = 'story'"
            >
              Story Bible
            </button>
            <button
              class="tab-button"
              :class="{ active: activeOutputTab === 'episodes' }"
              type="button"
              title="Episodes"
              aria-label="Episodes"
              @click="activeOutputTab = 'episodes'"
            >
              Episodes
            </button>
            <button
              class="tab-button"
              :class="{ active: activeOutputTab === 'storyboards' }"
              type="button"
              title="Storyboards"
              aria-label="Storyboards"
              @click="activeOutputTab = 'storyboards'"
            >
              Storyboards
            </button>
          </div>

          <div v-if="!projectSummary" class="empty-state">
            No output project is available yet. Run `/docs` to load a new `output/&lt;project&gt;/`.
          </div>

          <div v-else-if="busy.project" class="empty-state">
            <div class="loading-stack">
              <span class="spinner-ring" aria-hidden="true"></span>
              <span>Loading project...</span>
            </div>
          </div>

          <div v-else-if="activeOutputTab === 'story'" class="story-grid">
            <section class="story-summary">
              <div class="metric-card">
                <span>Characters</span>
                <strong>{{ storyCharacters.length }}</strong>
              </div>
              <div class="metric-card">
                <span>Props</span>
                <strong>{{ storyProps.length }}</strong>
              </div>
              <div class="metric-card">
                <span>Locations</span>
                <strong>{{ storyBackground.locations?.length || 0 }}</strong>
              </div>
            </section>

            <details class="entity-block collapsible-block">
              <summary class="collapsible-summary">
                <div>
                  <h3>Main Characters</h3>
                  <p class="collapsible-meta">{{ storyCharacters.length }} characters</p>
                </div>
              </summary>
              <div class="table-shell">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Aliases</th>
                      <th>Type</th>
                      <th>Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="character in storyCharacters" :key="character.name">
                      <td class="cell-strong">{{ character.name }}</td>
                      <td>{{ joinList(character.aliases) }}</td>
                      <td>{{ character.role_type || 'Uncategorized' }}</td>
                      <td>{{ character.summary || '--' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>

            <details class="entity-block collapsible-block">
              <summary class="collapsible-summary">
                <div>
                  <h3>Props & World</h3>
                  <p class="collapsible-meta">
                    {{ storyProps.length }} props, {{ storyBackground.locations?.length || 0 }} locations
                  </p>
                </div>
              </summary>
              <div class="table-stack">
                <div class="table-shell">
                  <table class="data-table">
                    <thead>
                      <tr>
                        <th>Prop</th>
                        <th>Purpose</th>
                        <th>Owner / User</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="prop in storyProps" :key="prop.name">
                        <td class="cell-strong">{{ prop.name }}</td>
                        <td>{{ prop.purpose || '--' }}</td>
                        <td>{{ prop.owner_or_user || '--' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div class="table-shell">
                  <table class="data-table data-table-compact">
                    <thead>
                      <tr>
                        <th>Dimension</th>
                        <th>Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in storyBackgroundRows" :key="row.label">
                        <td class="cell-strong">{{ row.label }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </details>

            <details class="json-block">
              <summary>View raw story_bible.json</summary>
              <pre>{{ prettyJson(storyBible) }}</pre>
            </details>
          </div>

          <div v-else-if="activeOutputTab === 'episodes'" class="preview-grid">
            <aside class="preview-list">
              <button
                v-for="episode in episodeItems"
                :key="episode.episode_no"
                class="preview-list-item"
                :class="{ active: selectedEpisodeNo === episode.episode_no }"
                type="button"
                @click="openEpisode(episode.episode_no)"
              >
                <strong>Episode {{ String(episode.episode_no).padStart(2, '0') }}</strong>
                <span>{{ episode.file }}</span>
              </button>
            </aside>

            <section v-if="episodeDetail" class="preview-detail">
              <div class="detail-head">
                <h3>
                  {{
                    episodeDetail.generated_content?.title ||
                    episodeDetail.episode_plan?.title ||
                    'Episode Preview'
                  }}
                </h3>
                <span class="muted">source units: {{ episodeDetail.source_units?.join(', ') || '--' }}</span>
              </div>

              <div class="detail-card">
                <h4>Summary</h4>
                <p>{{ episodeDetail.generated_content?.short_summary || 'No summary available.' }}</p>
              </div>

              <div class="detail-card">
                <h4>Core Beats</h4>
                <ul class="plain-list">
                  <li v-for="beat in episodeDetail.episode_plan?.core_beats || []" :key="beat">
                    {{ beat }}
                  </li>
                </ul>
              </div>

              <details class="json-block">
                <summary>View script and JSON</summary>
                <pre>{{ episodeDetail.generated_content?.script || prettyJson(episodeDetail) }}</pre>
              </details>
            </section>

            <section v-else class="empty-state empty-state-compact">
              No episode preview is available.
            </section>
          </div>

          <div v-else class="preview-grid">
            <aside class="preview-list">
              <button
                v-for="storyboard in storyboardItems"
                :key="storyboard.episode_no"
                class="preview-list-item"
                :class="{ active: selectedStoryboardNo === storyboard.episode_no }"
                type="button"
                @click="openStoryboard(storyboard.episode_no)"
              >
                <strong>Storyboard {{ String(storyboard.episode_no).padStart(2, '0') }}</strong>
                <span>coverage {{ storyboard.dialogue_coverage_rate ?? '--' }}</span>
              </button>
            </aside>

            <section v-if="storyboardDetail" class="preview-detail">
              <div class="detail-head">
                <h3>{{ storyboardDetail.storyboard?.title || 'Storyboard Preview' }}</h3>
                <span class="muted">
                  scenes: {{ storyboardDetail.storyboard?.scenes?.length || 0 }}
                </span>
              </div>

              <div class="detail-card storyboard-metrics">
                <div class="metric-card">
                  <span>Dialogue Coverage</span>
                  <strong>{{ formatRate(storyboardDetail.validation?.dialogue_coverage_rate) }}</strong>
                </div>
                <div class="metric-card">
                  <span>Unknown Props</span>
                  <strong>{{ storyboardDetail.validation?.unknown_props?.length || 0 }}</strong>
                </div>
                <div class="metric-card">
                  <span>Unknown Characters</span>
                  <strong>{{ storyboardDetail.validation?.unknown_characters?.length || 0 }}</strong>
                </div>
              </div>

              <div class="detail-card">
                <h4>Validation</h4>
                <ul class="plain-list">
                  <li>Dialogue coverage: {{ formatRate(storyboardDetail.validation?.dialogue_coverage_rate) }}</li>
                  <li>Missing dialogues: {{ storyboardDetail.validation?.missing_dialogues?.length || 0 }}</li>
                  <li>Unknown props: {{ joinList(storyboardDetail.validation?.unknown_props) }}</li>
                  <li>Unknown characters: {{ joinList(storyboardDetail.validation?.unknown_characters) }}</li>
                </ul>
              </div>

              <div class="detail-card">
                <h4>Scene Preview</h4>
                <div class="storyboard-scene-list">
                  <article
                    v-for="scene in storyboardDetail.storyboard?.scenes || []"
                    :key="scene.scene_no"
                    class="storyboard-scene-card"
                  >
                    <div class="storyboard-scene-head">
                      <strong>Scene {{ scene.scene_no }}</strong>
                      <span>{{ scene.shots?.length || 0 }} shots</span>
                    </div>

                    <div class="storyboard-shot-list">
                      <article
                        v-for="shot in scene.shots || []"
                        :key="`${scene.scene_no}-${shot.shot_no}`"
                        class="storyboard-shot-card"
                      >
                        <div class="storyboard-shot-head">
                          <strong>Shot {{ shot.shot_no }}</strong>
                          <span>{{ formatDuration(shot.duration) }}</span>
                        </div>
                        <p class="storyboard-label">Purpose</p>
                        <p>{{ shot.purpose || '--' }}</p>
                        <p class="storyboard-label">Characters</p>
                        <p>{{ joinList(shot.characters) }}</p>
                        <p class="storyboard-label">Visual</p>
                        <p>{{ shot.visual || '--' }}</p>
                        <p v-if="shot.dialogue" class="storyboard-label">Dialogue</p>
                        <p v-if="shot.dialogue">{{ shot.dialogue }}</p>
                      </article>
                    </div>
                  </article>
                </div>
              </div>

              <details class="json-block">
                <summary>View storyboard JSON</summary>
                <pre>{{ prettyJson(storyboardDetail) }}</pre>
              </details>
            </section>

            <section v-else class="empty-state empty-state-compact">
              No storyboard preview is available.
            </section>
          </div>
        </article>
      </template>
    </section>
  </main>
</template>
