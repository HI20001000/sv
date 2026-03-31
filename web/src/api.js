const API_PREFIX = '/api'

async function request(path, options = {}) {
  const response = await fetch(`${API_PREFIX}${path}`, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`)
  }
  return data
}

export function getHealth() {
  return request('/health')
}

export function getInputDocuments() {
  return request('/input-documents')
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
