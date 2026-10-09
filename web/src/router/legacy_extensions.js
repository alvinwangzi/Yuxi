/** 将旧扩展书签转到唯一资源入口，保留业务查询与详情锚点。 */
export function redirectLegacyExtensions(route) {
  const { tab, ...query } = route.query
  const resourceTabs = ['mcp', 'tools', 'skills', 'connectors', 'channels']
  const path = resourceTabs.includes(tab) ? '/skills' : '/knowledge'
  if (path === '/skills' && tab !== 'skills') query.tab = tab
  return { path, query, hash: route.hash }
}
