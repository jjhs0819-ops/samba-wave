'use client'

import React, { useState, useCallback } from 'react'
import {
  collectorApi,
  type SambaCollectedProduct,
} from '@/lib/samba/api/commerce'
import { fmtNum } from '@/lib/samba/styles'

/** ?ë“­ë€¡ ?â‘¤ê¼¸ ???ë“­ë€¡ï§?åª›Â€å¯ƒ??Ñˆí€¬ ?ëª„ì­› + ?ì‡¨íµ?ì„ì ™. */
const OptionPanel = React.memo(function OptionPanel({ options, productCost, productId, sourceSite }: { options: unknown[]; productCost: number; productId: string; sourceSite: string }) {
  const [open, setOpen] = useState(false)
  const [selectAll, setSelectAll] = useState(true)
  const [editingName, setEditingName] = useState<number | null>(null)
  const [localOpts, setLocalOpts] = useState(options as Record<string, unknown>[])
  const [bulkModal, setBulkModal] = useState<'price' | 'stock' | 'addOption' | null>(null)
  const [bulkValue, setBulkValue] = useState('')
  // åª›ì’•í€Ž ?ë“­ë€¡ åª›Â€å¯ƒ??Ñˆí€¬ ?ëª„ì­› ?ê³¹ê¹­ (?ëªƒëœ³?????ì’–ë–†åª›?
  const [editingPrices, setEditingPrices] = useState<Record<number, string>>({})
  const [editingStocks, setEditingStocks] = useState<Record<number, string>>({})
  const opts = localOpts

  const getOptionLabel = useCallback((opt: Record<string, unknown>, idx: number) => {
    const names = [opt.optionName1, opt.optionName2, opt.optionName3]
      .map(v => String(v || '').trim())
      .filter(Boolean)
    if (names.length > 0) return names.join('/')
    return String(opt.name || opt.value || `?ë“­ë€¡${idx + 1}`)
  }, [])

  // ?ë“­ë€¡ è¹‚Â€å¯ƒ???ï§ë±ë–† API ?Â€??
  const saveOptions = useCallback((newOpts: Record<string, unknown>[]) => {
    setLocalOpts(newOpts)
    collectorApi.updateProduct(productId, { options: newOpts } as Partial<SambaCollectedProduct>).catch(() => {})
  }, [productId])

  // ?ì‡¨íµ?ì„ì ™ ?ê³¸ìŠœ (åª›Â€å¯ƒ??ë¨®ë’— ?Ñˆí€¬)
  const applyBulk = useCallback((mode: 'price' | 'stock', value: string) => {
    const v = parseInt(value, 10)
    if (isNaN(v)) return
    if (mode === 'price') {
      // React ?ê³¹ê¹­æ¿¡?åª›Â€å¯ƒ??ë‚…ì °åª›??ì‡¨íµ åª›ê¹†ë–Š
      const newPrices: Record<number, string> = {}
      opts.forEach((_, idx) => { newPrices[idx] = fmtNum(v) })
      setEditingPrices(newPrices)
      saveOptions(opts.map(o => ({ ...o, salePrice: v })))
    } else {
      // React ?ê³¹ê¹­æ¿¡??Ñˆí€¬ ?ë‚…ì °åª›??ì‡¨íµ åª›ê¹†ë–Š
      const newStocks: Record<number, string> = {}
      opts.forEach((_, idx) => { newStocks[idx] = String(v) })
      setEditingStocks(newStocks)
      saveOptions(opts.map(o => ({ ...o, stock: v })))
    }
  }, [opts, saveOptions])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ color: '#888', fontSize: '0.78rem' }}>{fmtNum(opts.length)}åª›??ë“­ë€¡</span>
        <button
          onClick={() => setOpen(!open)}
          style={{
            fontSize: '0.7rem', padding: '2px 8px',
            border: '1px solid #2D2D2D', borderRadius: '4px',
            color: '#888', background: 'transparent', cursor: 'pointer',
          }}
        >
          {open ? '?ë¬Žë¦°' : '?ì‡±íŠ‚æ¹²?}
        </button>
      </div>
      {open && (
        <div style={{ marginTop: '8px' }}>
          {/* ?ëˆê¶¡è‡¾ë©¸ëŽ„ */}
          <p style={{ fontSize: '0.72rem', color: '#888', marginBottom: '0.75rem', lineHeight: 1.5 }}>
            ???ë“­ë€¡è¹‚ê¾¨ì¤ˆ åª›Â€å¯ƒ?è«›??Ñˆí€¬ ?ì„ì ™??åª›Â€?Î½ë¹€?ëˆë–Ž. åª›Â€å¯ƒ??Ñˆí€¬ç‘œ??ì„ì ™?ì„ë–†ï§Ž??ëŒì‡… åª›Â€å¯ƒ??Ñˆí€¬??è‡¾ëŒë–†?ì„í€¬, ?ì„ì ™?ì„ë–Š åª›Â€å¯ƒ??Ñˆí€¬æ¿¡?è«›ì„ìº?â‘¸ë•²??<br />
            ??ï§£ëŒ„ê²•è«›ëº¤ë’ª??ï§£ëŒ„ê²•?ì„ë¼± ?ëˆë’— ?ê³¹ë­¹ï§?ï§ë‰í†?ì‡°ì¤ˆ ?ê¾©ë„š?â‘¸ë•²?? ?ê¾©ë„š???ë¨°ë¸¯ï§žÂ€ ?ë”…ë’— ?ë“­ë€¡?Â€ ï§£ëŒ„ê²•ç‘œ??ëŒì £?ì„ë–Š ???ë“­ë€¡?Â€??è¸°ê¾ªë“‰???ëŒ€â”ƒ?ëŒï¼œ?ëª„ìŠ‚.
          </p>

          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                <th style={{ width: '36px', padding: '0.5rem', textAlign: 'center' }}>
                  <input type="checkbox" checked={selectAll} onChange={(e) => setSelectAll(e.target.checked)} style={{ cursor: 'pointer', accentColor: '#FF8C00' }} />
                </th>
                <th style={{ padding: '0.5rem', textAlign: 'center', fontSize: '0.8rem', color: '#999', fontWeight: 500 }}>
                  ?ë“­ë€¡ï§?                  <button
                    onClick={() => setEditingName(editingName === -1 ? null : -1)}
                    style={{ marginLeft: '0.4rem', fontSize: '0.7rem', padding: '1px 6px', background: editingName === -1 ? 'rgba(255,140,0,0.3)' : 'rgba(255,140,0,0.15)', color: '#FF8C00', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '3px', cursor: 'pointer' }}
                  >{editingName === -1 ? '?ëª„ì­›?ê¾¨ì¦º' : '?ë“­ë€¡ï§ë‚…?å¯ƒ?}</button>
                  <button
                    onClick={() => { setBulkModal('addOption'); setBulkValue('') }}
                    style={{ marginLeft: '0.3rem', fontSize: '0.7rem', padding: '1px 6px', background: 'rgba(255,255,255,0.05)', color: '#C5C5C5', border: '1px solid #3D3D3D', borderRadius: '3px', cursor: 'pointer' }}
                  >?ë“­ë€¡ç•°ë¶½?</button>
                </th>
                <th style={{ padding: '0.5rem', textAlign: 'center', fontSize: '0.8rem', color: '#999', fontWeight: 500 }}>
                  ?ë¨­?<br /><span style={{ fontSize: '0.7rem', color: '#555', fontWeight: 400 }}>(?ì‡°ì»²è«›ê³—ë„š)</span>
                </th>
                {sourceSite === 'KREAM' && (
                  <th style={{ padding: '0.5rem', textAlign: 'center', fontSize: '0.8rem', color: '#999', fontWeight: 500 }}>
                    é®ì¢Šâ…¨è«›ê³—ë„š<br /><span style={{ fontSize: '0.7rem', color: '#555', fontWeight: 400 }}>(KREAM)</span>
                  </th>
                )}
                <th style={{ padding: '0.5rem', textAlign: 'center', fontSize: '0.8rem', color: '#999', fontWeight: 500 }}>
                  ?ê³¹ë­¹åª›Â€<br />
                  <button
                    onClick={() => { setBulkModal('price'); setBulkValue('') }}
                    style={{ fontSize: '0.7rem', padding: '1px 6px', background: 'rgba(255,255,255,0.05)', color: '#C5C5C5', border: '1px solid #3D3D3D', borderRadius: '3px', cursor: 'pointer', marginTop: '2px' }}
                  >?ì‡¨íµ?ì„ì ™</button>
                </th>
                <th style={{ padding: '0.5rem', textAlign: 'center', fontSize: '0.8rem', color: '#999', fontWeight: 500 }}>
                  ?ë“­ë€¡?Ñˆí€¬
                  <button
                    onClick={() => { setBulkModal('stock'); setBulkValue('') }}
                    style={{ marginLeft: '0.3rem', fontSize: '0.7rem', padding: '1px 6px', background: 'rgba(255,255,255,0.05)', color: '#C5C5C5', border: '1px solid #3D3D3D', borderRadius: '3px', cursor: 'pointer' }}
                  >?ì‡¨íµ?ì„ì ™</button>
                </th>
              </tr>
            </thead>
            <tbody>
              {opts.map((o, idx) => {
                const isBrandDelivery = o.isBrandDelivery === true
                const stock = o.stock !== undefined && o.stock !== null ? Number(o.stock) : -1
                const isSoldOut = !isBrandDelivery && (o.isSoldOut === true || stock === 0)
                const optionCost = isSoldOut ? 0 : productCost
                const optionSalePrice = Math.ceil(optionCost * 1.15)
                const isChecked = !isSoldOut

                // åª›Â€å¯ƒ??ì’–ë–†: ?ëª„ì­› ?ê³¹ê¹­åª›?> salePrice > æ€¨ê¾©ê¶›åª›?
                const priceDisplay = editingPrices[idx] ?? (
                  optionSalePrice > 0 ? fmtNum(optionSalePrice) : '0'
                )

                let stockDisplay: React.ReactNode
                if (isBrandDelivery) {
                  stockDisplay = <span style={{ color: '#6B8AFF', fontWeight: 600, fontSize: '0.78rem' }}>é‡‰ëš®ì˜–?ì’•ê°™??/span>
                } else if (isSoldOut) {
                  stockDisplay = <span style={{ color: '#FF6B6B', fontWeight: 600 }}>?ë‰ì …</span>
                } else if (stock < 0 || stock >= 999) {
                  stockDisplay = (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      <input
                        type="number"
                        value={editingStocks[idx] ?? ''}
                        placeholder=""
                        onChange={(e) => setEditingStocks(prev => ({ ...prev, [idx]: e.target.value }))}
                        style={{ width: '70px', background: 'rgba(255,255,255,0.05)', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', textAlign: 'right', fontSize: '0.875rem' }}
                      />
                      <span style={{ fontSize: '0.72rem', color: '#51CF66' }}>{stock >= 999 ? 'ç•°â‘¸í…‡' : '?Ñˆí€¬?ë‰ì“¬'}</span>
                    </span>
                  )
                } else {
                  stockDisplay = (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      <input
                        type="number"
                        value={editingStocks[idx] ?? String(stock)}
                        onChange={(e) => setEditingStocks(prev => ({ ...prev, [idx]: e.target.value }))}
                        style={{ width: '60px', background: 'rgba(255,255,255,0.05)', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', textAlign: 'right', fontSize: '0.875rem' }}
                      />
                      <span>åª›?/span>
                    </span>
                  )
                }

                const optionName1 = String(o.optionName1 || '').trim()
                const optionName2 = String(o.optionName2 || '').trim()
                const optionName3 = String(o.optionName3 || '').trim()

                return (
                  <tr key={idx} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)', opacity: isSoldOut ? 0.5 : 1 }}>
                    <td style={{ padding: '0.5rem', textAlign: 'center' }}>
                      <input type="checkbox" defaultChecked={isChecked} style={{ cursor: 'pointer', accentColor: '#FF8C00' }} />
                    </td>
                    <td style={{ padding: '0.5rem', fontSize: '0.875rem', color: '#E5E5E5' }}>
                      {editingName === -1 ? (
                        <input
                          type="text"
                          defaultValue={getOptionLabel(o, idx)}
                          onBlur={(e) => {
                            const newOpts = [...opts]
                            newOpts[idx] = { ...newOpts[idx], name: e.target.value }
                            saveOptions(newOpts)
                          }}
                          style={{ width: '100%', background: 'rgba(255,255,255,0.05)', border: '1px solid #FF8C00', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.875rem' }}
                        />
                      ) : optionName1 && optionName2 ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', lineHeight: 1.35 }}>
                          <span>{optionName1}</span>
                          <span style={{ color: '#C5C5C5', fontSize: '0.82rem' }}>
                            {[optionName2, optionName3].filter(Boolean).join(' / ')}
                          </span>
                        </div>
                      ) : (
                        getOptionLabel(o, idx)
                      )}
                    </td>
                    <td style={{ padding: '0.5rem', textAlign: 'right', fontSize: '0.875rem', color: '#C5C5C5' }}>
                      {sourceSite === 'KREAM'
                        ? (Number(o.kreamGeneralPrice || o.kreamNormalPrice || o.price || 0) > 0 ? `??{fmtNum(Number(o.kreamGeneralPrice || o.kreamNormalPrice || o.price || 0))}` : '-')
                        : (optionCost > 0 ? `??{fmtNum(optionCost)}` : '-')
                      }
                    </td>
                    {sourceSite === 'KREAM' && (
                      <td style={{ padding: '0.5rem', textAlign: 'right', fontSize: '0.875rem', color: '#6B8AFF' }}>
                        {Number(o.kreamFastPrice || 0) > 0 ? `??{fmtNum(Number(o.kreamFastPrice))}` : '-'}
                      </td>
                    )}
                    <td style={{ padding: '0.5rem', textAlign: 'right', fontSize: '0.875rem', color: '#E5E5E5', whiteSpace: 'nowrap' }}>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={priceDisplay}
                        onChange={(e) => {
                          setEditingPrices(prev => ({ ...prev, [idx]: e.target.value }))
                        }}
                        onFocus={(e) => {
                          // ?ÑŠë¹±????è‚„ã…»ì­ ?ì’“êµ…?ì„ë¿¬ ?ëª„ì­› ?â‘¹ì” ?ì„ì¾¶
                          setEditingPrices(prev => ({ ...prev, [idx]: e.target.value.replace(/,/g, '') }))
                        }}
                        onBlur={(e) => {
                          // é‡‰ë¶¾ìœ­ ???ãƒ¬ì˜„ ?Ñ‰ãŽŽ???ê³¸ìŠœ
                          const v = parseInt(e.target.value.replace(/,/g, ''), 10)
                          setEditingPrices(prev => ({ ...prev, [idx]: isNaN(v) ? '0' : fmtNum(v) }))
                        }}
                        style={{ width: '80px', background: 'rgba(255,255,255,0.05)', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', textAlign: 'right', fontSize: '0.875rem' }}
                      />
                      <span style={{ marginLeft: '2px' }}>??/span>
                    </td>
                    <td style={{ padding: '0.5rem', textAlign: 'right', fontSize: '0.875rem', color: '#E5E5E5' }}>
                      {stockDisplay}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {/* ?ì‡¨íµ?ì„ì ™ ï§â‘¤ë–– */}
          {bulkModal && (
            <div style={{
              position: 'fixed', inset: 0, zIndex: 99998,
              background: 'rgba(0,0,0,0.6)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }} onClick={() => setBulkModal(null)}>
              <div style={{
                background: '#1E1E1E', border: '1px solid #3D3D3D', borderRadius: '10px',
                padding: '20px 24px', width: 'min(360px, 90vw)',
              }} onClick={e => e.stopPropagation()}>
                <h4 style={{ margin: '0 0 12px', fontSize: '0.85rem', color: '#E5E5E5' }}>
                  {bulkModal === 'price' ? '?ê³¹ë­¹åª›Â€ ?ì‡¨íµ?ì„ì ™' : bulkModal === 'stock' ? '?ë“­ë€¡?Ñˆí€¬ ?ì‡¨íµ?ì„ì ™' : '?ë“­ë€¡ ç•°ë¶½?'}
                </h4>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="text"
                    inputMode={bulkModal === 'addOption' ? 'text' : 'numeric'}
                    autoFocus
                    placeholder={bulkModal === 'price' ? 'åª›Â€å¯ƒ??ë‚…ì ° (??' : bulkModal === 'stock' ? '?Ñˆí€¬ ?ë‚…ì ° (åª›?' : '?ë“­ë€¡ï§??ë‚…ì °'}
                    value={bulkValue}
                    onChange={e => setBulkValue(bulkModal === 'addOption' ? e.target.value : e.target.value.replace(/[^0-9]/g, ''))}
                    onKeyDown={e => {
                      if (e.key !== 'Enter') return
                      if (bulkModal === 'addOption') {
                        if (bulkValue.trim()) {
                          saveOptions([...opts, { name: bulkValue.trim(), price: productCost, stock: 0, isSoldOut: false }])
                          setBulkModal(null)
                        }
                      } else {
                        applyBulk(bulkModal, bulkValue)
                        setBulkModal(null)
                      }
                    }}
                    style={{ flex: 1, padding: '8px 12px', fontSize: '0.85rem', background: '#1A1A1A', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '6px' }}
                  />
                  {bulkModal !== 'addOption' && <span style={{ color: '#888', fontSize: '0.8rem' }}>{bulkModal === 'price' ? '?? : 'åª›?}</span>}
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
                  <button onClick={() => setBulkModal(null)}
                    style={{ padding: '6px 16px', fontSize: '0.8rem', borderRadius: '6px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>ç—â‘¥ëƒ¼</button>
                  <button onClick={() => {
                    if (bulkModal === 'addOption') {
                      if (bulkValue.trim()) {
                        saveOptions([...opts, { name: bulkValue.trim(), price: productCost, stock: 0, isSoldOut: false }])
                      }
                    } else {
                      applyBulk(bulkModal, bulkValue)
                    }
                    setBulkModal(null)
                  }} style={{ padding: '6px 16px', fontSize: '0.8rem', borderRadius: '6px', border: 'none', background: '#FF8C00', color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
                    {bulkModal === 'addOption' ? 'ç•°ë¶½?' : '?ê³¸ìŠœ'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
})

export default OptionPanel
