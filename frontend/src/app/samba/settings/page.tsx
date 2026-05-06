'use client'

import { useEffect, useState } from 'react'
import { tenantApi, type TenantUsage } from '@/lib/samba/api/operations'
import { useProxySettings } from './hooks/useProxySettings'
import { ProxySettingsPanel } from './components/ProxySettingsPanel'
import { useExternalSettings } from './hooks/useExternalSettings'
import { ExternalIntegrationsPanel } from './components/ExternalIntegrationsPanel'
import { useStoreSettings } from './hooks/useStoreSettings'
import { StoreSettingsPanel } from './components/StoreSettingsPanel'
import { useSourcingAccounts } from './hooks/useSourcingAccounts'
import { SourcingAccountsPanel } from './components/SourcingAccountsPanel'
import { LicensePanel } from './components/LicensePanel'
import { DailyJobSettingsPanel } from './components/DailyJobSettingsPanel'
import { card, fmtNum } from '@/lib/samba/styles'

export default function SettingsPage() {
  useEffect(() => { document.title = 'SAMBA-설정' }, [])

  // 티어/사용량
  const [tenantUsage, setTenantUsage] = useState<TenantUsage | null>(null)

  // 훅
  const proxySettings = useProxySettings()
  const externalSettings = useExternalSettings()
  const storeSettings = useStoreSettings()
  const sourcingAccountsHook = useSourcingAccounts()
  const { loadSourcingAccounts } = sourcingAccountsHook

  const { loadAccounts, loadStoreSettings } = storeSettings
  const { loadExchangeRates, loadExternalSettings, loadProbeStatus } = externalSettings
  const { loadProxies } = proxySettings

  useEffect(() => {
    loadAccounts()
    loadSourcingAccounts()
    loadProxies()
    tenantApi.getMyUsage().then(setTenantUsage).catch(() => {})
  }, [loadAccounts, loadSourcingAccounts, loadProxies])

  useEffect(() => {
    loadExchangeRates()
    loadExternalSettings()
    loadProbeStatus()
    loadStoreSettings()
  }, [loadExchangeRates, loadExternalSettings, loadProbeStatus, loadStoreSettings])

  return (
    <div style={{ color: '#E5E5E5' }}>
      <DailyJobSettingsPanel
        networkIps={storeSettings.networkIps}
        networkIpStatus={storeSettings.networkIpStatus}
        setNetworkIps={storeSettings.setNetworkIps}
        saveNetworkIps={storeSettings.saveNetworkIps}
      />

      <StoreSettingsPanel {...storeSettings} />

      {/* 소싱처 계정 관리 */}
      <SourcingAccountsPanel {...sourcingAccountsHook} />

      {/* 플랜 / 사용량 */}
      {tenantUsage?.usage && (() => {
        const PLAN_LABELS: Record<string, string> = { free: 'Free', basic: 'Basic', pro: 'Pro', enterprise: 'Enterprise' }
        const PLAN_COLORS: Record<string, string> = { free: '#666', basic: '#4C9AFF', pro: '#FF8C00', enterprise: '#A855F7' }
        const planColor = PLAN_COLORS[tenantUsage.plan] || '#666'
        const items = [
          { label: '상품', ...tenantUsage.usage.products },
          { label: '마켓', ...tenantUsage.usage.markets },
          { label: '소싱', ...tenantUsage.usage.sourcing },
        ]
        return (
          <div style={{ ...card, padding: '1.25rem', marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
              <span style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>플랜</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 700, color: planColor, background: `${planColor}18`, padding: '0.2rem 0.6rem', borderRadius: '4px' }}>
                {PLAN_LABELS[tenantUsage.plan] || tenantUsage.plan}
              </span>
              {tenantUsage.autotune_enabled && (
                <span style={{ fontSize: '0.6875rem', color: '#22C55E', background: '#22C55E18', padding: '0.15rem 0.5rem', borderRadius: '4px' }}>오토튠 ON</span>
              )}
              {tenantUsage.subscription_end && (
                <span style={{ fontSize: '0.6875rem', color: '#666', marginLeft: 'auto' }}>
                  만료: {new Date(tenantUsage.subscription_end).toLocaleDateString('ko-KR')}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: '1.5rem' }}>
              {items.map(({ label, current, max }) => {
                const isUnlimited = max === -1
                const pct = isUnlimited ? 0 : Math.min((current / max) * 100, 100)
                const barColor = pct >= 90 ? '#EF4444' : pct >= 70 ? '#F59E0B' : '#4C9AFF'
                return (
                  <div key={label} style={{ flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#999', marginBottom: '0.35rem' }}>
                      <span>{label}</span>
                      <span>{fmtNum(current)} / {isUnlimited ? '무제한' : fmtNum(max)}</span>
                    </div>
                    <div style={{ height: '6px', background: '#1A1A1A', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ width: isUnlimited ? '0%' : `${pct}%`, height: '100%', background: barColor, borderRadius: '3px', transition: 'width 0.3s' }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}

      <ExternalIntegrationsPanel
        {...externalSettings}
        visiblePasswords={storeSettings.visiblePasswords}
        togglePasswordVisibility={storeSettings.togglePasswordVisibility}
      />

      {/* 프록시 설정 */}
      <ProxySettingsPanel {...proxySettings} />

      {/* 라이선스 */}
      <LicensePanel />
    </div>
  )
}
