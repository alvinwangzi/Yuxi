import { apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

export const channelApi = {
  listChannels() {
    return apiAdminGet('/api/system/channels')
  },

  getChannel(slug) {
    return apiAdminGet(`/api/system/channels/${slug}`)
  },

  createChannel(data) {
    return apiAdminPost('/api/system/channels', data)
  },

  updateChannel(slug, data) {
    return apiAdminPut(`/api/system/channels/${slug}`, data)
  },

  deleteChannel(slug) {
    return apiAdminDelete(`/api/system/channels/${slug}`)
  },

  testChannel(slug) {
    return apiAdminPost(`/api/system/channels/${slug}/test`)
  },

  listChannelTypes() {
    return apiAdminGet('/api/system/channels/types')
  },

  startFeishuRegistration() {
    return apiAdminPost('/api/system/channels/feishu/register')
  },

  getFeishuRegistrationStatus(registrationId) {
    return apiAdminGet(`/api/system/channels/feishu/register/${registrationId}`)
  }
}
