'use client'

import { card, inputStyle, fmtNum } from '@/lib/samba/styles'
import { forbiddenApi, proxyApi } from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'
import { NumInputStr as NumInput } from '@/components/samba/NumInput'
import { API_BASE } from '@/lib/samba/api/shared'
import {
  CLAUDE_MODELS,
  EXCHANGE_CURRENCY_ORDER,
  getExchangeDisplayMultiplier,
} from '../config'
import type { ExternalSettingsState, ExternalSettingsActions } from '../hooks/useExternalSettings'

type Props = ExternalSettingsState & ExternalSettingsActions & {
  visiblePasswords: Set<string>
  togglePasswordVisibility: (key: string) => void
}

export function ExternalIntegrationsPanel(props: Props) {
  const {
    // 환율
    exchangeRates, exchangeStatus, exchangeSaving,
    loadExchangeRates, saveExchangeSettings, updateExchangeField,
    // SMS
    smsUserId, smsApiKey, smsSender, smsStatus,
    setSmsUserId, setSmsApiKey, setSmsSender,
    saveSmsSettings, testSmsKey,
    // 카카오
    kakaoUserId, kakaoApiKey, kakaoSenderKey, kakaoSender, kakaoStatus,
    setKakaoUserId, setKakaoApiKey, setKakaoSenderKey, setKakaoSender,
    saveKakaoSettings, testKakaoKey,
    // Gemini
    geminiApiKey, geminiModel, geminiStatus,
    setGeminiApiKey, setGeminiModel,
    testGeminiApi, saveGeminiSettings,
    // R2
    r2AccountId, r2AccessKey, r2SecretKey, r2BucketName, r2PublicUrl, r2Status,
    setR2AccountId, setR2AccessKey, setR2SecretKey, setR2BucketName, setR2PublicUrl,
    saveR2Settings, testR2,
    // Claude
    claudeApiKey, claudeModel, claudeStatus, aiFeatures,
    setClaudeApiKey, setClaudeModel,
    saveClaudeSettings, testClaudeApi, toggleAiFeature,
    // 프리셋
    presets, editingPreset, editingDesc, editingLabel, regenerating, presetZoom,
    setEditingPreset, setEditingDesc, setEditingLabel, setRegenerating, setPresetZoom,
    loadPresets, handleSavePreset, handleRegeneratePreset,
    // 금지어/삭제어
    forbiddenText, deletionText, optionDeletionText, wordsSaving,
    setForbiddenText, setDeletionText, setOptionDeletionText,
    setWordsSaving, setInitialForbiddenText, setInitialDeletionText, setInitialOptionDeletionText,
    // 태그 금지어
    tagBanned, setTagBanned,
    // 공통
    visiblePasswords, togglePasswordVisibility,
  } = props

  return (
    <>
      {/* 환율 설정 */}
      <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.35rem' }}>
          <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>환율 설정</div>
          <span style={{ fontSize: '0.75rem', color: '#888' }}>
            해외 소싱가를 원화 계산가로 바꿀 때 사용됩니다.
          </span>
          <button
            onClick={() => loadExchangeRates(true)}
            style={{ marginLeft: 'auto', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', color: '#4C9AFF', padding: '0.35rem 0.8rem', borderRadius: '6px', fontSize: '0.78rem', cursor: 'pointer' }}
          >
            최신환율 새로고침
          </button>
          <button
            onClick={saveExchangeSettings}
            disabled={exchangeSaving}
            style={{ background: exchangeSaving ? '#333' : 'rgba(255,140,0,0.16)', border: '1px solid rgba(255,140,0,0.35)', color: exchangeSaving ? '#777' : '#FF8C00', padding: '0.35rem 0.8rem', borderRadius: '6px', fontSize: '0.78rem', cursor: exchangeSaving ? 'not-allowed' : 'pointer' }}
          >
            환율 저장
          </button>
        </div>
        <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1rem' }}>
          + / - 조정은 기준 환율에 가감되고, 고정 환율을 입력하면 해당 통화는 고정값이 우선 적용됩니다.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.875rem' }}>
          {EXCHANGE_CURRENCY_ORDER.map((code) => {
            const item = exchangeRates.currencies[code]
            const multiplier = getExchangeDisplayMultiplier(code)
            const unitLabel = code === 'JPY' ? '100' : '1'
            return (
              <div key={code} style={{ background: '#161616', border: '1px solid #2D2D2D', borderRadius: '10px', padding: '0.9rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <div>
                    <div style={{ fontSize: '0.88rem', fontWeight: 700, color: '#E5E5E5' }}>{item.label}</div>
                    <div style={{ fontSize: '0.72rem', color: '#777' }}>{code} {unitLabel} = ₩{fmtNum(Math.round(item.effectiveRate * multiplier))}</div>
                  </div>
                  <span style={{ fontSize: '0.68rem', color: item.useFixed ? '#FF8C00' : '#4C9AFF' }}>
                    {item.useFixed ? '고정 적용' : '실시간 적용'}
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
                  <div>
                    <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>기준 환율</div>
                    <div style={{ ...inputStyle, color: '#A3A3A3' }}>₩{fmtNum(Math.round(item.baseRate * multiplier))}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>+ / - 조정</div>
                    <NumInput
                      style={{ width: '100%' }}
                      value={String((item.adjustment || 0) * multiplier)}
                      onChange={(value) => updateExchangeField(code, 'adjustment', value)}
                      placeholder="0"
                    />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>고정 환율</div>
                    <NumInput
                      style={{ width: '100%' }}
                      value={item.fixedRate ? String(item.fixedRate * multiplier) : ''}
                      onChange={(value) => updateExchangeField(code, 'fixedRate', value)}
                      placeholder="비워두면 실시간"
                    />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>계산 환율</div>
                    <div style={{ ...inputStyle, color: '#FF8C00', fontWeight: 700 }}>₩{fmtNum(Math.round(item.effectiveRate * multiplier))}</div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginTop: '0.9rem', fontSize: '0.75rem', color: '#666' }}>
          <span>통화 매핑: Amazon/eBay/Shopify=USD, Rakuten/BUYMA=JPY, Poizon/Zoom=CNY</span>
          <span>{exchangeStatus || (exchangeRates.publishedAt ? `기준 시각: ${String(exchangeRates.publishedAt)}` : '')}</span>
        </div>
      </div>

      {/* SMS / 카카오 알림톡 설정 */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.5rem' }}>

        {/* SMS 설정 */}
        <div style={{ paddingBottom: '1.5rem', marginBottom: '1.5rem', borderBottom: '1px solid #2D2D2D' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#4C9AFF' }}>SMS 설정</span>
            <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 알리고(ALIGO) 문자메세지 설정을 할 수 있습니다.</span>
            {smsStatus && <span style={{ fontSize: '0.8rem', color: smsStatus === '저장됨' || smsStatus.includes('유효') ? '#51CF66' : smsStatus.includes('오류') ? '#FF6B6B' : '#FFD93D' }}>{smsStatus === '저장됨' ? '✓ 저장됨' : smsStatus}</span>}
            <a href="https://smartsms.aligo.in/admin/api/info.html" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
            <button onClick={saveSmsSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'nowrap' }}>
              <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem', flexShrink: 0 }}>SMS API KEY</label>
              <input style={{ ...inputStyle, flex: 2, minWidth: '100px' }} value={smsUserId} onChange={(e) => setSmsUserId(e.target.value)} placeholder='Identifier' />
              <input style={{ ...inputStyle, flex: 4, minWidth: '140px' }} value={smsApiKey} onChange={(e) => setSmsApiKey(e.target.value)} placeholder='API Key' />
              <button onClick={() => window.open('https://www.aligo.in/index.html', '_blank')} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>Key 발급</button>
              <button onClick={testSmsKey} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>테스트</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>SMS 발신번호</label>
              <input style={{ ...inputStyle, width: '160px', flexShrink: 0 }} value={smsSender} onChange={(e) => setSmsSender(e.target.value)} placeholder='010-0000-0000' />
              <span style={{ fontSize: '0.8125rem', color: '#FF6B6B' }}>※ 발신번호는 사전에 알리고에 등록하신 후 입력해주시기 바랍니다.</span>
            </div>
          </div>
        </div>

        {/* 카카오 알림톡 설정 */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FFB84D' }}>카카오 알림톡 설정</span>
            <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 알리고(ALIGO) 카카오 알림톡 설정을 할 수 있습니다.</span>
            {kakaoStatus && <span style={{ fontSize: '0.8rem', color: kakaoStatus === '저장됨' || kakaoStatus.includes('유효') ? '#51CF66' : kakaoStatus.includes('오류') ? '#FF6B6B' : '#FFD93D' }}>{kakaoStatus === '저장됨' ? '✓ 저장됨' : kakaoStatus}</span>}
            <a href="https://smartsms.aligo.in/admin/api/kakao.html" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
            <button onClick={saveKakaoSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'nowrap' }}>
              <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem', flexShrink: 0 }}>알림톡 API KEY</label>
              <input style={{ ...inputStyle, flex: 2, minWidth: '100px' }} value={kakaoUserId} onChange={(e) => setKakaoUserId(e.target.value)} placeholder='Identifier' />
              <input style={{ ...inputStyle, flex: 4, minWidth: '140px' }} value={kakaoApiKey} onChange={(e) => setKakaoApiKey(e.target.value)} placeholder='API Key' />
              <button onClick={() => window.open('https://www.aligo.in/index.html', '_blank')} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>Key 발급</button>
              <button onClick={testKakaoKey} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>테스트</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>알림톡 SenderKey</label>
              <input style={{ ...inputStyle, flex: 1 }} value={kakaoSenderKey} onChange={(e) => setKakaoSenderKey(e.target.value)} placeholder='Senderkey를 입력하세요.' />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>알림톡 발신번호</label>
              <input style={{ ...inputStyle, width: '160px', flexShrink: 0 }} value={kakaoSender} onChange={(e) => setKakaoSender(e.target.value)} placeholder='010-0000-0000' />
              <span style={{ fontSize: '0.8125rem', color: '#FF6B6B' }}>※ 발신번호는 사전에 알리고에 등록하신 후 입력해주시기 바랍니다.</span>
            </div>
          </div>
        </div>
      </div>

      {/* Gemini AI (이미지 변환 / AI태그) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#4285F4' }}>Gemini AI (이미지 변환 / AI태그)</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>상품사진 → 모델착용컷 생성 (₩430/장)</span>
          <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(66,133,244,0.1)', border: '1px solid rgba(66,133,244,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4285F4', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
          <button onClick={saveGeminiSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
        </div>
        <div style={{ maxWidth: '720px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>API Key</label>
            <div style={{ display: 'flex', flex: 1, gap: '4px', alignItems: 'center' }}>
              <input type={visiblePasswords.has('gemini_apiKey') ? 'text' : 'password'} style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={geminiApiKey} onChange={(e) => setGeminiApiKey(e.target.value)} placeholder='AIzaSy...' />
              <button type="button" onClick={() => togglePasswordVisibility('gemini_apiKey')} style={{ padding: '0.3rem 0.5rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer', whiteSpace: 'nowrap' }}>{visiblePasswords.has('gemini_apiKey') ? '숨김' : '보기'}</button>
            </div>
            <button onClick={testGeminiApi} style={{ background: 'rgba(66,133,244,0.1)', border: '1px solid rgba(66,133,244,0.35)', color: '#4285F4', padding: '0.35rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>연결 테스트</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>모델</label>
            <select style={{ ...inputStyle, width: '300px' }} value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)}>
              <option value="gemini-2.5-flash-lite">Gemini 2.5 Flash Lite (권장)</option>
              <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
              <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
            </select>
          </div>
          {geminiStatus && (
            <div style={{ fontSize: '0.8125rem', color: geminiStatus.includes('저장') ? '#7BAF7E' : '#C4736E', padding: '0.4rem 0' }}>
              {geminiStatus}
            </div>
          )}
        </div>
      </div>

      {/* Cloudflare R2 연동 (이미지 저장) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#F59E0B' }}>Cloudflare R2 연동</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 변환된 이미지 저장용 (미설정 시 서버 로컬 저장)</span>
          <a href="https://dash.cloudflare.com/?to=/:account/r2/api-tokens" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
          <button onClick={saveR2Settings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
        </div>
        <div style={{ maxWidth: '720px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Account ID</label>
            <input type='text' style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={r2AccountId} onChange={(e) => setR2AccountId(e.target.value)} placeholder='Cloudflare Account ID' />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Access Key ID</label>
            <input type='text' style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={r2AccessKey} onChange={(e) => setR2AccessKey(e.target.value)} placeholder='R2 Access Key ID' />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Secret Access Key</label>
            <div style={{ display: 'flex', flex: 1, gap: '4px', alignItems: 'center' }}>
              <input type={visiblePasswords.has('r2_secretKey') ? 'text' : 'password'} style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={r2SecretKey} onChange={(e) => setR2SecretKey(e.target.value)} placeholder='R2 Secret Access Key' />
              <button type="button" onClick={() => togglePasswordVisibility('r2_secretKey')} style={{ padding: '0.3rem 0.5rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer', whiteSpace: 'nowrap' }}>{visiblePasswords.has('r2_secretKey') ? '숨김' : '보기'}</button>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Bucket Name</label>
            <input type='text' style={{ ...inputStyle, flex: 1 }} value={r2BucketName} onChange={(e) => setR2BucketName(e.target.value)} placeholder='samba-images' />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Public URL</label>
            <input type='text' style={{ ...inputStyle, flex: 1 }} value={r2PublicUrl} onChange={(e) => setR2PublicUrl(e.target.value)} placeholder='https://pub-xxx.r2.dev' />
            <button onClick={testR2} style={{ background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.35)', color: '#F59E0B', padding: '0.35rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>연결 테스트</button>
          </div>
          {r2Status && (
            <div style={{ fontSize: '0.8125rem', color: r2Status.includes('저장') || r2Status.includes('✓') ? '#7BAF7E' : r2Status.includes('확인') ? '#FFB84D' : '#C4736E', padding: '0.4rem 0' }}>
              {r2Status}
            </div>
          )}
        </div>
      </div>

      {/* Claude AI API 연동 */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#A78BFA' }}>Claude AI API 연동</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** Anthropic Claude API를 연결하면 상품명 가공, CS 자동 답변 등 AI 기능을 사용할 수 있습니다.</span>
          <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
          <button onClick={saveClaudeSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
        </div>
        <div style={{ maxWidth: '720px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>API Key</label>
            <div style={{ display: 'flex', flex: 1, gap: '4px', alignItems: 'center' }}>
              <input
                type={visiblePasswords.has('claude_apiKey') ? 'text' : 'password'}
                style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }}
                value={claudeApiKey}
                onChange={(e) => setClaudeApiKey(e.target.value)}
                placeholder='sk-ant-api03-...'
              />
              <button type="button" onClick={() => togglePasswordVisibility('claude_apiKey')} style={{ padding: '0.3rem 0.5rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer', whiteSpace: 'nowrap' }}>{visiblePasswords.has('claude_apiKey') ? '숨김' : '보기'}</button>
            </div>
            <button onClick={testClaudeApi} style={{ background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.35)', color: '#A78BFA', padding: '0.35rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>연결 테스트</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>모델 선택</label>
            <select style={{ ...inputStyle, width: '260px' }} value={claudeModel} onChange={(e) => setClaudeModel(e.target.value)}>
              {CLAUDE_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          {claudeStatus && (
            <div style={{ fontSize: '0.8125rem', color: claudeStatus.includes('저장') ? '#51CF66' : claudeStatus.includes('유효') ? '#FFB84D' : '#FF6B6B', padding: '0.4rem 0' }}>
              {claudeStatus.includes('저장') ? '✓ ' : claudeStatus.includes('유효') ? '⚠ ' : '✗ '}{claudeStatus}
            </div>
          )}
        </div>
      </div>

      {/* AI 모델 프리셋 관리 */}
      {presets.length > 0 && (
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FF8C00' }}>AI 모델 프리셋</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 모델 착용 이미지 생성 시 참조하는 기준 모델</span>
          <button onClick={loadPresets} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>새로고침</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '1rem' }}>
          {presets.map(p => (
            <div key={p.key} style={{ background: 'rgba(30,30,30,0.6)', borderRadius: '8px', border: '1px solid #2D2D2D', overflow: 'hidden' }}>
              <div style={{ position: 'relative', paddingTop: '120%', background: '#1A1A1A' }}>
                {p.image ? (
                  <img
                    src={`${API_BASE}${p.image}?t=${Date.now()}`}
                    alt={p.label}
                    style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover', cursor: 'pointer' }}
                    onClick={() => setPresetZoom(`${API_BASE}${p.image}?t=${Date.now()}`)}
                  />
                ) : (
                  <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', color: '#555', fontSize: '0.7rem', textAlign: 'center' }}>이미지 없음</div>
                )}
                {/* 이미지 업로드 버튼 */}
                <button
                  style={{ position: 'absolute', bottom: 4, right: 4, background: 'rgba(0,0,0,0.7)', border: '1px solid #555', color: '#CCC', borderRadius: '4px', padding: '2px 6px', fontSize: '0.6rem', cursor: 'pointer' }}
                  onClick={() => {
                    const input = document.createElement('input')
                    input.type = 'file'
                    input.accept = 'image/*'
                    input.onchange = async (e) => {
                      const file = (e.target as HTMLInputElement).files?.[0]
                      if (!file) return
                      setRegenerating(p.key)
                      try {
                        const res = await proxyApi.uploadPresetImage(p.key, file)
                        if (res.success) {
                          showAlert(res.message, 'success')
                          await loadPresets()
                        } else {
                          showAlert(res.message, 'error')
                        }
                      } catch {
                        showAlert('업로드 실패', 'error')
                      } finally {
                        setRegenerating(null)
                      }
                    }
                    input.click()
                  }}
                >업로드</button>
                {regenerating === p.key && (
                  <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#FF8C00', fontSize: '0.75rem' }}>
                    처리중...
                  </div>
                )}
              </div>
              <div style={{ padding: '0.5rem' }}>
                {editingPreset === p.key ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    <input
                      value={editingLabel}
                      onChange={e => setEditingLabel(e.target.value)}
                      style={{ ...inputStyle, fontSize: '0.7rem', fontWeight: 600 }}
                      placeholder="프리셋 이름"
                    />
                    <textarea
                      value={editingDesc}
                      onChange={e => setEditingDesc(e.target.value)}
                      rows={3}
                      style={{ ...inputStyle, fontSize: '0.7rem', resize: 'vertical' }}
                      placeholder="모델 설명 프롬프트"
                    />
                    <div style={{ display: 'flex', gap: '0.25rem' }}>
                      <button
                        onClick={() => handleRegeneratePreset(p.key, editingDesc, editingLabel)}
                        disabled={regenerating !== null}
                        style={{ flex: 1, padding: '0.2rem', fontSize: '0.65rem', background: 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '4px', color: '#FF8C00', cursor: 'pointer' }}
                      >저장 & 재생성</button>
                      <button
                        onClick={() => handleSavePreset(p.key, editingLabel, editingDesc)}
                        style={{ flex: 1, padding: '0.2rem', fontSize: '0.65rem', background: 'rgba(255,255,255,0.08)', border: '1px solid #444', borderRadius: '4px', color: '#CCC', cursor: 'pointer' }}
                      >저장만</button>
                      <button
                        onClick={() => setEditingPreset(null)}
                        style={{ padding: '0.2rem 0.4rem', fontSize: '0.65rem', background: 'rgba(255,80,80,0.1)', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '4px', color: '#FF6B6B', cursor: 'pointer' }}
                      >취소</button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '0.2rem' }}>{p.label}</div>
                    <div style={{ fontSize: '0.65rem', color: '#888', marginBottom: '0.35rem', lineHeight: 1.3 }}>{p.desc.length > 40 ? p.desc.slice(0, 40) + '...' : p.desc}</div>
                    <button
                      onClick={() => { setEditingPreset(p.key); setEditingLabel(p.label); setEditingDesc(p.desc) }}
                      style={{ width: '100%', padding: '0.2rem', fontSize: '0.65rem', background: 'rgba(255,255,255,0.05)', border: '1px solid #333', borderRadius: '4px', color: '#AAA', cursor: 'pointer' }}
                    >수정</button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
      )}

      {/* 금지어 / 삭제어 (전역) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#E5E5E5' }}>금지어 / 삭제어</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>모든 그룹·상품에 공통 적용</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#FF6B6B', fontWeight: 600 }}>
                금지어 (IP위험 브랜드 포함) — 세미콜론(;) 구분
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(forbiddenText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('forbidden', words)
                    const deduped = words.join('; ')
                    setForbiddenText(deduped)
                    setInitialForbiddenText(deduped)
                    showAlert(`금지어 ${words.length}개 저장 완료`, 'success')
                  } catch {
                    showAlert('저장 실패', 'error')
                  }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.3)',
                  color: '#FF6B6B', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={forbiddenText}
              onChange={e => setForbiddenText(e.target.value)}
              placeholder="구찌; 루이비통; 샤넬; 프라다"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {forbiddenText.split(';').filter(w => w.trim()).length}개
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#FFB84D', fontWeight: 600 }}>
                삭제어 — 상품명에서 자동 제거
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(deletionText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('deletion', words)
                    const deduped = words.join('; ')
                    setDeletionText(deduped)
                    setInitialDeletionText(deduped)
                    const { showAlert } = await import('@/components/samba/Modal')
                    showAlert(`삭제어 ${words.length}개 저장 완료`, 'success')
                  } catch {
                    showAlert('저장 실패', 'error')
                  }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(255,184,77,0.12)', border: '1px solid rgba(255,184,77,0.3)',
                  color: '#FFB84D', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={deletionText}
              onChange={e => setDeletionText(e.target.value)}
              placeholder="매장정품; 정품; 해외직구; 무료배송"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {deletionText.split(';').filter(w => w.trim()).length}개
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#A29BFE', fontWeight: 600 }}>
                옵션삭제어 — 옵션명에서 자동 제거
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(optionDeletionText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('option_deletion', words)
                    const deduped = words.join('; ')
                    setOptionDeletionText(deduped)
                    setInitialOptionDeletionText(deduped)
                    const { showAlert } = await import('@/components/samba/Modal')
                    showAlert(`옵션삭제어 ${words.length}개 저장 완료`, 'success')
                  } catch {
                    showAlert('저장 실패', 'error')
                  }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(162,155,254,0.12)', border: '1px solid rgba(162,155,254,0.3)',
                  color: '#A29BFE', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={optionDeletionText}
              onChange={e => setOptionDeletionText(e.target.value)}
              placeholder="01(; 02(; ); [품절]"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {optionDeletionText.split(';').filter(w => w.trim()).length}개
            </div>
          </div>
        </div>
      </div>

      {/* 태그 금지어 (스마트스토어 등록불가 단어) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#C4736E' }}>태그 금지어</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 스마트스토어 등록 시 자동 제외되는 단어 (API 거부 + 소싱처 + 브랜드)</span>
          <button onClick={() => forbiddenApi.getTagBannedWords().then(setTagBanned).catch(() => {})}
            style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>새로고침</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* API 거부 태그 */}
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#C4736E', fontWeight: 600, marginBottom: '0.4rem' }}>
              API 거부 태그 ({tagBanned.rejected.length}개)
              <span style={{ fontWeight: 400, color: '#666', marginLeft: '0.5rem' }}>전송 실패 시 자동 누적 + 직접 추가 가능</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
              {tagBanned.rejected.length === 0 && <span style={{ fontSize: '0.75rem', color: '#555' }}>아직 없음</span>}
              {tagBanned.rejected.map((w, i) => (
                <span key={i} style={{
                  fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px',
                  background: 'rgba(196,115,110,0.12)', border: '1px solid rgba(196,115,110,0.3)', color: '#C4736E',
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                }}>
                  {w}
                  <span style={{ cursor: 'pointer', color: '#888', fontSize: '0.8rem', lineHeight: 1 }}
                    onClick={async () => {
                      const updated = tagBanned.rejected.filter((_, idx) => idx !== i)
                      await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                      setTagBanned(prev => ({ ...prev, rejected: updated }))
                    }}>×</span>
                </span>
              ))}
              <input
                type="text"
                placeholder="금지어 입력 후 Enter"
                style={{ fontSize: '0.7rem', padding: '2px 7px', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#C5C5C5', background: '#1A1A1A', outline: 'none', width: '140px' }}
                onKeyDown={async (e) => {
                  if (e.key === 'Enter') {
                    const val = e.currentTarget.value.trim().toLowerCase()
                    if (!val || tagBanned.rejected.includes(val)) return
                    const updated = [...tagBanned.rejected, val]
                    await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                    setTagBanned(prev => ({ ...prev, rejected: updated }))
                    e.currentTarget.value = ''
                  }
                }}
              />
            </div>
          </div>
          {/* 수집 브랜드 */}
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#FFB84D', fontWeight: 600, marginBottom: '0.4rem' }}>
              수집 브랜드 ({tagBanned.brands.length}개)
              <span style={{ fontWeight: 400, color: '#666', marginLeft: '0.5rem' }}>브랜드명 포함 태그 자동 제외</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', maxHeight: '80px', overflow: 'auto' }}>
              {tagBanned.brands.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(255,184,77,0.08)', border: '1px solid rgba(255,184,77,0.25)', color: '#FFB84D' }}>{w}</span>
              ))}
            </div>
          </div>
          {/* 소싱처 */}
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#4C9AFF', fontWeight: 600, marginBottom: '0.4rem' }}>
              소싱처 ({tagBanned.source_sites.length}개)
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
              {tagBanned.source_sites.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(76,154,255,0.08)', border: '1px solid rgba(76,154,255,0.25)', color: '#4C9AFF' }}>{w}</span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 프리셋 이미지 확대 모달 */}
      {presetZoom && (
        <div
          onClick={() => setPresetZoom(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'zoom-out' }}
        >
          <img src={presetZoom} alt="프리셋 확대" style={{ maxWidth: '90vw', maxHeight: '90vh', objectFit: 'contain', borderRadius: '8px' }} />
        </div>
      )}
    </>
  )
}
