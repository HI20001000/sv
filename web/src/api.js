const API_PREFIX = '/api'

async function request(path, options = {}) {
  const response = await fetch(`${API_PREFIX}${path}`, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = data.detail
    const message = typeof detail === 'string' ? detail : detail?.message || `Request failed: ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.data = data
    throw error
  }
  return data
}

export function getHealth() {
  return request('/health')
}

export function getInputDocuments() {
  return request('/input-documents')
}

export function getKnowledgeBase() {
  return request('/knowledge-base')
}

export function checkKnowledgeBaseFilename(filename) {
  return request(`/knowledge-base/check-filename?filename=${encodeURIComponent(filename)}`)
}

export function uploadKnowledgeBaseFile(file, options = {}) {
  const formData = new FormData()
  formData.append('file', file)
  if (options.overwriteRecordId) {
    formData.append('overwrite_record_id', options.overwriteRecordId)
  }
  return request('/knowledge-base/upload-and-extract', {
    method: 'POST',
    body: formData,
  })
}

export function getKnowledgeBaseJob(jobId) {
  return request(`/knowledge-base/jobs/${encodeURIComponent(jobId)}`)
}

export function getKnowledgeBaseItem(recordId) {
  return request(`/knowledge-base/items/${encodeURIComponent(recordId)}`)
}

export function uploadInputDocument(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/input-documents', {
    method: 'POST',
    body: formData,
  })
}

export function deleteInputDocument(filename) {
  return request(`/input-documents/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  })
}

export function getOutputProjects() {
  return request('/output/projects')
}

export function getPrompts() {
  return request('/prompts')
}

export function getPrompt(promptKey) {
  return request(`/prompts/${encodeURIComponent(promptKey)}`)
}

export function updatePrompt(promptKey, content) {
  return request(`/prompts/${encodeURIComponent(promptKey)}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content }),
  })
}

export function getOutputProject(projectName) {
  return request(`/output/projects/${encodeURIComponent(projectName)}`)
}

export function getEpisode(projectName, episodeNo) {
  return request(`/output/projects/${encodeURIComponent(projectName)}/episodes/${episodeNo}`)
}

export function getStoryboard(projectName, episodeNo) {
  return request(`/output/projects/${encodeURIComponent(projectName)}/storyboards/${episodeNo}`)
}

export function runWorkflow(filename) {
  return request('/workflow/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ filename }),
  })
}

export function getWorkflowJob(jobId) {
  return request(`/workflow/jobs/${encodeURIComponent(jobId)}`)
}

export function sendChatMessage(message) {
  return request('/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message }),
  })
}
