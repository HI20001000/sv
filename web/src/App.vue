<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  deleteInputDocument,
  getEpisode,
  getHealth,
  getInputDocuments,
  getOutputProject,
  getOutputProjects,
  getStoryboard,
  getWorkflowJob,
  runWorkflow,
  sendChatMessage,
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

const chatInput = ref('')
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
    { label: '時代', value: formatInlineValue(background.era) },
    { label: '主要場景', value: formatInlineValue(background.locations) },
    { label: '社會背景', value: formatInlineValue(background.social_context) },
    { label: '世界規則', value: formatInlineValue(background.world_rules) },
  ].filter((item) => item.value !== '--')
})
const episodeItems = computed(() => projectBundle.value?.episodes_index?.episodes || [])
const storyboardItems = computed(() => projectBundle.value?.storyboards_index?.episodes || [])
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
  return new Intl.DateTimeFormat('zh-Hant', {
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
    }
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
  if (!window.confirm(`刪除 ${filename}？`)) return

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
    notice.value = '請先選擇要處理的文件。'
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
})

onBeforeUnmount(() => {
  workflowPollers.forEach((timer) => {
    window.clearInterval(timer)
  })
  workflowPollers.clear()
})
</script>

<template>
  <main class="workspace-shell">
    <header class="topbar">
      <div class="topbar-copy">
        <p class="panel-kicker">Short Video AI Console</p>
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

    <section class="workspace-grid">
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
              @click="fileInput?.click()"
            >
              {{ busy.upload ? '上傳中...' : '上傳文件' }}
            </button>
            <button
              class="primary-button"
              type="button"
              :disabled="busy.workflow || !selectedDocument"
              @click="handleRunWorkflow()"
            >
              {{ busy.workflow ? '處理中...' : '執行 /docs' }}
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
            <button class="danger-link" type="button" @click.stop="handleDelete(doc.name)">
              刪除
            </button>
          </article>
        </div>

        <div v-else class="empty-state">
          `input_documents` 目前沒有文件。先上傳一個劇本檔案，再執行 `/docs`。
        </div>
      </article>

      <article class="panel panel-chat">
        <div class="panel-head">
          <div>
            <p class="panel-kicker">Chat Console</p>
          </div>
        </div>

        <div class="chat-stream">
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
              <span>{{ busy.workflow ? '工作流處理中...' : '正在生成回應...' }}</span>
            </div>
          </article>
        </div>

        <form class="chat-composer" @submit.prevent="handleChatSubmit">
          <textarea
            v-model="chatInput"
            rows="4"
            placeholder="輸入你的訊息，或使用 /docs filename、/ping、/clear..."
          />
          <button class="primary-button" type="submit" :disabled="busy.chat">
            {{ busy.chat ? '送出中...' : '送出' }}
          </button>
        </form>
      </article>

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
            <option value="" disabled>選擇輸出項目</option>
            <option v-for="project in projects" :key="project.name" :value="project.name">
              {{ project.name }}
            </option>
          </select>
        </div>

        <div v-if="projectSummary" class="project-overview">
          <div class="overview-card">
            <span>來源文件</span>
            <strong>{{ projectSummary.source_file || 'Unknown' }}</strong>
          </div>
          <div class="overview-card">
            <span>建立時間</span>
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
            @click="activeOutputTab = 'story'"
          >
            Story Bible
          </button>
          <button
            class="tab-button"
            :class="{ active: activeOutputTab === 'episodes' }"
            type="button"
            @click="activeOutputTab = 'episodes'"
          >
            Episodes
          </button>
          <button
            class="tab-button"
            :class="{ active: activeOutputTab === 'storyboards' }"
            type="button"
            @click="activeOutputTab = 'storyboards'"
          >
            Storyboards
          </button>
        </div>

        <div v-if="!projectSummary" class="empty-state">
          目前還沒有可預覽的輸出項目。先執行一次 `/docs`，這裡就會載入新的 `output/&lt;project&gt;/`。
        </div>

        <div v-else-if="busy.project" class="empty-state">
          <div class="loading-stack">
            <span class="spinner-ring" aria-hidden="true"></span>
            <span>正在載入項目資料...</span>
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
                <h3>主要角色</h3>
                <p class="collapsible-meta">共 {{ storyCharacters.length }} 位角色</p>
              </div>
            </summary>
            <div class="table-shell">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>角色</th>
                    <th>別名</th>
                    <th>類型</th>
                    <th>摘要</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="character in storyCharacters" :key="character.name">
                    <td class="cell-strong">{{ character.name }}</td>
                    <td>{{ joinList(character.aliases) }}</td>
                    <td>{{ character.role_type || '未分類' }}</td>
                    <td>{{ character.summary || '--' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </details>

          <details class="entity-block collapsible-block">
            <summary class="collapsible-summary">
              <div>
                <h3>重要道具與世界觀</h3>
                <p class="collapsible-meta">道具 {{ storyProps.length }} 項，場景 {{ storyBackground.locations?.length || 0 }} 個</p>
              </div>
            </summary>
            <div class="table-stack">
              <div class="table-shell">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>道具</th>
                      <th>用途</th>
                      <th>使用者 / 所屬</th>
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
                      <th>世界觀維度</th>
                      <th>內容</th>
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
            <summary>查看 story_bible.json 原始內容</summary>
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
                {{ episodeDetail.generated_content?.title || episodeDetail.episode_plan?.title || 'Episode Preview' }}
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
                <li v-for="beat in episodeDetail.episode_plan?.core_beats || []" :key="beat">{{ beat }}</li>
              </ul>
            </div>

            <details class="json-block">
              <summary>查看劇集腳本與 JSON</summary>
              <pre>{{ episodeDetail.generated_content?.script || prettyJson(episodeDetail) }}</pre>
            </details>
          </section>

          <section v-else class="empty-state empty-state-compact">
            目前沒有可預覽的劇集內容。
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
              <summary>查看 storyboard JSON</summary>
              <pre>{{ prettyJson(storyboardDetail) }}</pre>
            </details>
          </section>

          <section v-else class="empty-state empty-state-compact">
            目前沒有可預覽的分鏡內容。
          </section>
        </div>
      </article>
    </section>
  </main>
</template>
