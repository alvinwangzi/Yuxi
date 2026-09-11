import { apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

export const channelApi = {
  listChannels() {
    return apiAdminGet('/system/channels')
  },

  getChannel(slug) {
    return apiAdminGet(`/system/channels/${slug}`)
  },

  createChannel(data) {
    return apiAdminPost('/system/channels', data)
  },

  updateChannel(slug, data) {
    return apiAdminPut(`/system/channels/${slug}`, data)
  },

  deleteChannel(slug) {
    return apiAdminDelete(`/system/channels/${slug}`)
  },

  testChannel(slug) {
    return apiAdminPost(`/system/channels/${slug}/test`)
  },

  listChannelTypes() {
    return apiAdminGet('/system/channels/types')
  }
}
