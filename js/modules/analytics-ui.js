/**
 * 매출통계 / 대시보드 UI 모듈
 * 차트 초기화, 필터, 뷰 전환, KPI 카드 업데이트
 */

/* ──────────────────────────────────────────
   매출통계 페이지
────────────────────────────────────────── */
let acCharts = {}

// 뷰 전환 (차트 ↔ 테이블)
function acView(type) {
  const isChart = type === 'chart'
  document.getElementById('ac-charts-view').style.display = isChart ? '' : 'none'
  document.getElementById('ac-tables-view').style.display = isChart ? 'none' : ''
  document.getElementById('ac-btn-chart').classList.toggle('ac-active', isChart)
  document.getElementById('ac-btn-table').classList.toggle('ac-active', !isChart)
  if (isChart) setTimeout(initAcCharts, 30)
  else initAcTables()
}

// 체크박스 그룹 전체 토글
function afToggleAll(group, allCb) {
  document.querySelectorAll('.af-' + group).forEach(cb => {
    cb.checked = allCb.checked
  })
}

// 초기화: 모든 체크박스 해제
function afResetAll() {
  ;['mkt', 'site', 'status'].forEach(g => {
    document.querySelectorAll('.af-' + g).forEach(cb => cb.checked = false)
    const allCb = document.getElementById('af-all-' + g)
    if (allCb) allCb.checked = false
  })
}

// 필터 조건을 읽어 실제 주문 데이터로 집계
function acSearch() {
  const selYear = parseInt(document.getElementById('af-year').value) || new Date().getFullYear()
  const selMonthStr = document.getElementById('af-month').value || ''
  const selMonth = selMonthStr ? parseInt(selMonthStr) : null

  const checkedMkts = [...document.querySelectorAll('.af-mkt:checked')].map(cb => cb.value)
  const checkedSites = [...document.querySelectorAll('.af-site:checked')].map(cb => cb.value)
  const checkedStatus = [...document.querySelectorAll('.af-status:checked')].map(cb => cb.value)

  if (typeof orderManager === 'undefined') return

  let orders = orderManager.orders.filter(o => {
    const d = new Date(o.createdAt)
    if (d.getFullYear() !== selYear) return false
    if (selMonth !== null && (d.getMonth() + 1) !== selMonth) return false
    return true
  })

  if (checkedMkts.length > 0) {
    orders = orders.filter(o => {
      const ch = (typeof channelManager !== 'undefined')
        ? channelManager.channels.find(c => c.id === o.channelId)
        : null
      const name = ch ? ch.name : (o.channelName || '')
      return checkedMkts.some(m => name.includes(m))
    })
  }

  if (checkedSites.length > 0) {
    orders = orders.filter(o => checkedSites.some(s => (o.sourceSite || '').includes(s)))
  }

  if (checkedStatus.length > 0) {
    orders = orders.filter(o => checkedStatus.includes(o.status))
  }

  const totalSales = orders.reduce((s, o) => s + (o.salePrice || 0), 0)
  const totalProfit = orders.reduce((s, o) => s + (o.profit || 0), 0)
  const totalOrders = orders.length
  const avgOrder = totalOrders > 0 ? Math.round(totalSales / totalOrders) : 0
  const profitRate = totalSales > 0 ? ((totalProfit / totalSales) * 100).toFixed(1) : 0

  const fn = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val }
  fn('kpi-total-sales', '₩' + totalSales.toLocaleString())
  fn('kpi-total-orders-sub', totalOrders + '건 주문 누적')
  fn('kpi-month-orders', totalOrders + '건')
  fn('kpi-month-label', selMonthStr ? selMonthStr + '월 기준' : selYear + '년 전체')
  fn('kpi-avg-order', '₩' + avgOrder.toLocaleString())
  fn('kpi-profit-rate', '마진율 ' + profitRate + '%')
  fn('kpi-total-profit', '₩' + totalProfit.toLocaleString())
  fn('kpi-profit-sub', '필터 조건 기준')

  // selMonth를 넘겨서 일별/월별 전환
  initAcTables(orders, selYear, selMonth, checkedMkts, checkedSites, checkedStatus)
}

// 테이블 탭 전환
function acTableTab(tab) {
  ;['mkt', 'site', 'status'].forEach(t => {
    document.getElementById('ac-tbl-' + t).style.display = 'none'
    document.getElementById('ac-tab-' + t).classList.remove('ac-tab-on')
  })
  document.getElementById('ac-tbl-' + tab).style.display = ''
  document.getElementById('ac-tab-' + tab).classList.add('ac-tab-on')
}

// ─────────────────────────────────────────────────────────
// 수익분석 표
// 컬럼: 기간 / 총매출(건수) / 이행매출(건수) / 수익금 / 수익률 / 주문이행율
// 총매출 = 필터 조건 무관, 해당 기간 전체 주문
// 이행매출 = orderNumber이 입력된 주문건 (필터 적용)
// selMonth 있으면 일별, 없으면 월별 행 출력
// ─────────────────────────────────────────────────────────
function initAcSummaryTable(filteredOrders, allOrders, selYear, selMonth) {
  const tbody = document.getElementById('acTblSummaryBody')
  if (!tbody) return

  const label = document.getElementById('ac-summary-label')

  // 행 단위 결정
  let rowLabels, getAllRowOrders, getFilteredRowOrders
  if (selMonth) {
    if (label) label.textContent = selYear + '년 ' + selMonth + '월 · 일별'
    const daysInMonth = new Date(selYear, selMonth, 0).getDate()
    rowLabels = Array.from({ length: daysInMonth }, (_, i) => `${i + 1}일`)
    getAllRowOrders = (i) => allOrders.filter(o => {
      const d = new Date(o.createdAt)
      return d.getFullYear() === selYear && (d.getMonth() + 1) === selMonth && d.getDate() === (i + 1)
    })
    getFilteredRowOrders = (i) => filteredOrders.filter(o => {
      const d = new Date(o.createdAt)
      return d.getFullYear() === selYear && (d.getMonth() + 1) === selMonth && d.getDate() === (i + 1)
    })
  } else {
    if (label) label.textContent = selYear + '년 · 월별'
    rowLabels = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
    getAllRowOrders = (i) => allOrders.filter(o => {
      const d = new Date(o.createdAt)
      return d.getFullYear() === selYear && (d.getMonth() + 1) === (i + 1)
    })
    getFilteredRowOrders = (i) => filteredOrders.filter(o => {
      const d = new Date(o.createdAt)
      return d.getFullYear() === selYear && (d.getMonth() + 1) === (i + 1)
    })
  }

  const rateColor = (r) => parseFloat(r) >= 15 ? '#51CF66' : parseFloat(r) >= 10 ? '#FFB84D' : '#888'
  const fulfillColor = (r) => parseFloat(r) >= 80 ? '#51CF66' : parseFloat(r) >= 50 ? '#FFB84D' : '#FC8181'
  const wonGreen = v => v ? `<span style="color:#51CF66;">₩${v.toLocaleString()}</span>` : '<span class="ac-cnt">-</span>'

  let tTotalSales = 0, tTotalCnt = 0, tFulfillSales = 0, tFulfillCnt = 0, tProfit = 0

  const rows = rowLabels.map((lbl, i) => {
    // 총매출: 필터 무관 전체 주문
    const allRow       = getAllRowOrders(i)
    const totalSales   = allRow.reduce((s, o) => s + (o.salePrice || 0), 0)
    const totalCnt     = allRow.length

    // 이행매출: 필터 적용 주문 중 orderNumber 입력된 것
    const filteredRow  = getFilteredRowOrders(i)
    const fulfilled    = filteredRow.filter(o => o.orderNumber && o.orderNumber.trim() !== '')
    const fulfillSales = fulfilled.reduce((s, o) => s + (o.salePrice || 0), 0)
    const fulfillCnt   = fulfilled.length
    const profit       = fulfilled.reduce((s, o) => s + (o.profit || 0), 0)
    const rate         = fulfillSales > 0 ? ((profit / fulfillSales) * 100).toFixed(1) : null
    const fulfillRate  = totalCnt > 0 ? ((fulfillCnt / totalCnt) * 100).toFixed(1) : null

    tTotalSales   += totalSales
    tTotalCnt     += totalCnt
    tFulfillSales += fulfillSales
    tFulfillCnt   += fulfillCnt
    tProfit       += profit

    return `<tr>
      <td style="white-space:nowrap;">${lbl}</td>
      <td>${totalSales ? `<span style="color:#C5C5C5;">₩${totalSales.toLocaleString()}</span> <span class="ac-cnt">${totalCnt}건</span>` : '<span class="ac-cnt">-</span>'}</td>
      <td>${fulfillSales ? `<span style="color:#C5C5C5;">₩${fulfillSales.toLocaleString()}</span> <span class="ac-cnt">${fulfillCnt}건</span>` : '<span class="ac-cnt">-</span>'}</td>
      <td>${wonGreen(profit)}</td>
      <td>${rate !== null ? `<span style="color:${rateColor(rate)};">${rate}%</span>` : '<span class="ac-cnt">-</span>'}</td>
      <td>${fulfillRate !== null ? `<span style="color:${fulfillColor(fulfillRate)};">${fulfillRate}%</span>` : '<span class="ac-cnt">-</span>'}</td>
    </tr>`
  })

  const tRate        = tFulfillSales > 0 ? ((tProfit / tFulfillSales) * 100).toFixed(1) : '0.0'
  const tFulfillRate = tTotalCnt > 0 ? ((tFulfillCnt / tTotalCnt) * 100).toFixed(1) : '0.0'

  tbody.innerHTML = rows.join('') + `<tr class="ac-sum-row">
    <td>합계</td>
    <td><span style="color:#FF8C00;">₩${tTotalSales.toLocaleString()}</span> <span class="ac-cnt">${tTotalCnt}건</span></td>
    <td><span style="color:#FF8C00;">₩${tFulfillSales.toLocaleString()}</span> <span class="ac-cnt">${tFulfillCnt}건</span></td>
    <td><span style="color:#51CF66;">₩${tProfit.toLocaleString()}</span></td>
    <td><span style="color:#FFB84D;">${tRate}%</span></td>
    <td><span style="color:${fulfillColor(tFulfillRate)};">${tFulfillRate}%</span></td>
  </tr>`
}

// ─────────────────────────────────────────────────────────
// 테이블 초기화 (실제 데이터 집계)
// selMonth 있으면 일별 행, 없으면 월별 행
// ─────────────────────────────────────────────────────────
function initAcTables(filteredOrders, selYear, selMonth, checkedMkts, checkedSites, checkedStatus) {
  const orders = filteredOrders || (typeof orderManager !== 'undefined' ? orderManager.orders : [])
  const year   = selYear || new Date().getFullYear()
  const fmt = v => v ? `<span style="color:#C5C5C5;">₩${v.toLocaleString()}</span>` : '<span class="ac-cnt">-</span>'
  const fmtOrange = v => v ? `<span style="color:#FF8C00;">₩${v.toLocaleString()}</span>` : '<span class="ac-cnt">-</span>'

  // 총매출용 전체 주문 (필터 무관, 연도+월만 적용)
  const allOrders = (typeof orderManager !== 'undefined') ? orderManager.orders.filter(o => {
    const d = new Date(o.createdAt)
    if (d.getFullYear() !== year) return false
    if (selMonth && (d.getMonth() + 1) !== selMonth) return false
    return true
  }) : []

  // 월 선택 여부에 따라 행 단위 결정
  let rowLabels, getRowOrders
  if (selMonth) {
    const daysInMonth = new Date(year, selMonth, 0).getDate()
    rowLabels = Array.from({ length: daysInMonth }, (_, i) => `${i + 1}일`)
    getRowOrders = (orders, i) => orders.filter(o => {
      const d = new Date(o.createdAt)
      return d.getFullYear() === year && (d.getMonth() + 1) === selMonth && d.getDate() === (i + 1)
    })
  } else {
    rowLabels = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
    getRowOrders = (orders, i) => orders.filter(o => {
      const d = new Date(o.createdAt)
      return d.getFullYear() === year && (d.getMonth() + 1) === (i + 1)
    })
  }

  // 요약 표 갱신 (총매출은 allOrders, 이행매출은 filtered orders)
  initAcSummaryTable(orders, allOrders, year, selMonth)

  // ── 마켓별 테이블 ──
  const mktNames = checkedMkts && checkedMkts.length > 0
    ? checkedMkts
    : (typeof MARKET_LIST !== 'undefined' && MARKET_LIST.length > 0
      ? MARKET_LIST
      : (typeof channelManager !== 'undefined'
        ? channelManager.channels.map(c => c.name)
        : []))

  const mktSet = new Set()
  orders.forEach(o => {
    const ch = (typeof channelManager !== 'undefined')
      ? channelManager.channels.find(c => c.id === o.channelId)
      : null
    const name = ch ? ch.name : (o.channelName || '')
    if (name) mktSet.add(name)
  })
  const mktList = mktNames.length > 0 ? mktNames : [...mktSet]

  const mktTable = document.getElementById('analytics-market-tbody')
  if (mktTable) {
    const mktThead = mktTable.closest('table')?.querySelector('thead tr')
    if (mktThead) {
      mktThead.innerHTML = `<th></th>` + mktList.map(m => `<th>${m}</th>`).join('') + `<th style="color:#FF8C00;">합계</th>`
    }
  }

  let mktHtml = ''
  const mktColTotals = mktList.map(() => 0)
  let mktGrandTotal = 0

  rowLabels.forEach((label, ri) => {
    const rowOrders = getRowOrders(orders, ri)
    const rowVals = mktList.map((mktName, si) => {
      const sum = rowOrders
        .filter(o => {
          const ch = (typeof channelManager !== 'undefined')
            ? channelManager.channels.find(c => c.id === o.channelId)
            : null
          const name = ch ? ch.name : (o.channelName || '')
          return name.includes(mktName)
        })
        .reduce((s, o) => s + (o.salePrice || 0), 0)
      mktColTotals[si] += sum
      return sum
    })
    const rowSum = rowVals.reduce((a, b) => a + b, 0)
    mktGrandTotal += rowSum
    mktHtml += `<tr><td style="white-space:nowrap;">${label}</td>${rowVals.map(v => `<td>${fmt(v)}</td>`).join('')}<td>${fmtOrange(rowSum)}</td></tr>`
  })
  mktHtml += `<tr class="ac-sum-row"><td>합계</td>${mktColTotals.map(v => `<td>${fmtOrange(v)}</td>`).join('')}<td>${fmtOrange(mktGrandTotal)}</td></tr>`
  document.getElementById('acTblMktBody').innerHTML = mktHtml

  // ── 사이트별 테이블 ──
  const allSites = (typeof SITE_LIST !== 'undefined') ? SITE_LIST : ['ABCmart','FOLDERStyle','GrandStage','GSShop','LOTTEON','MUSINSA','Nike','OliveYoung','SSG']
  const siteList = checkedSites && checkedSites.length > 0 ? checkedSites : allSites

  const siteTblEl = document.getElementById('acTblSiteBody')?.closest('table')
  if (siteTblEl) {
    const siteThead = siteTblEl.querySelector('thead tr')
    if (siteThead) {
      siteThead.innerHTML = `<th></th>` + siteList.map(s => `<th>${s}</th>`).join('') + `<th style="color:#FF8C00;">합계</th>`
    }
  }

  let siteHtml = ''
  const siteColTotals = siteList.map(() => 0)
  let siteGrandTotal = 0

  rowLabels.forEach((label, ri) => {
    const rowOrders = getRowOrders(orders, ri)
    const rowVals = siteList.map((siteName, si) => {
      const sum = rowOrders
        .filter(o => (o.sourceSite || '').includes(siteName))
        .reduce((s, o) => s + (o.salePrice || 0), 0)
      siteColTotals[si] += sum
      return sum
    })
    const rowSum = rowVals.reduce((a, b) => a + b, 0)
    siteGrandTotal += rowSum
    siteHtml += `<tr><td style="white-space:nowrap;">${label}</td>${rowVals.map(v => `<td>${fmt(v)}</td>`).join('')}<td>${fmtOrange(rowSum)}</td></tr>`
  })
  siteHtml += `<tr class="ac-sum-row"><td>합계</td>${siteColTotals.map(v => `<td>${fmtOrange(v)}</td>`).join('')}<td>${fmtOrange(siteGrandTotal)}</td></tr>`
  document.getElementById('acTblSiteBody').innerHTML = siteHtml

  // ── 주문상태별 테이블 ──
  const statusMap = {
    confirmed: '주문확인', waiting: '배송대기', arrived: '사무실도착',
    shipping: '국내배송', cancel_req: '취소요청', exchange_req: '교환요청',
    return_req: '반품요청', done: '완료', delivered: '배송완료'
  }
  const statusList = checkedStatus && checkedStatus.length > 0
    ? checkedStatus
    : Object.keys(statusMap)

  const statusTblEl = document.getElementById('acTblStatusBody')?.closest('table')
  if (statusTblEl) {
    const statusThead = statusTblEl.querySelector('thead tr')
    if (statusThead) {
      statusThead.innerHTML = `<th></th>` + statusList.map(s => `<th>${statusMap[s] || s}</th>`).join('') + `<th style="color:#FF8C00;">합계</th>`
    }
  }

  let statusHtml = ''
  const statusColCounts = statusList.map(() => 0)
  const statusColSales  = statusList.map(() => 0)
  let statusGrandTotal  = 0

  rowLabels.forEach((label, ri) => {
    const rowOrders = getRowOrders(orders, ri)
    const rowVals = statusList.map((st, si) => {
      const matched = rowOrders.filter(o => o.status === st)
      const sum = matched.reduce((s, o) => s + (o.salePrice || 0), 0)
      statusColCounts[si] += matched.length
      statusColSales[si]  += sum
      return { sum, cnt: matched.length }
    })
    const rowSum = rowVals.reduce((a, b) => a + b.sum, 0)
    statusGrandTotal += rowSum
    statusHtml += `<tr><td style="white-space:nowrap;">${label}</td>${rowVals.map(v => v.sum
      ? `<td><span style="color:#C5C5C5;">₩${v.sum.toLocaleString()}</span><br><span class="ac-cnt">${v.cnt}건</span></td>`
      : '<td><span class="ac-cnt">-</span></td>'
    ).join('')}<td>${fmtOrange(rowSum)}</td></tr>`
  })
  statusHtml += `<tr class="ac-sum-row"><td>합계</td>${statusColSales.map((v, i) => `<td>${fmtOrange(v)}<br><span class="ac-cnt">${statusColCounts[i]}건</span></td>`).join('')}<td>${fmtOrange(statusGrandTotal)}</td></tr>`
  document.getElementById('acTblStatusBody').innerHTML = statusHtml
}

// 차트 초기화
function initAcCharts() {
  if (typeof Chart === 'undefined') return
  Chart.defaults.color = '#555'
  Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
  const dkGrid = { color: 'rgba(255,255,255,0.035)', drawBorder: false }
  const tooltip = {
    backgroundColor: 'rgba(8,8,8,0.95)',
    borderColor: '#2D2D2D',
    borderWidth: 1,
    titleColor: '#C5C5C5',
    bodyColor: '#777',
    padding: 11,
    cornerRadius: 8
  }

  // 월별 매출 추이 라인
  const lineEl = document.getElementById('ac-line')
  if (lineEl) {
    if (acCharts.line) acCharts.line.destroy()
    acCharts.line = new Chart(lineEl.getContext('2d'), {
      type: 'line',
      data: {
        labels: ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'],
        datasets: [
          { label:'신세계몰', data:[52296000,29988400,11260900,...Array(9).fill(0)], borderColor:'#FF8C00', backgroundColor:'rgba(255,140,0,0.07)', borderWidth:2.5, tension:0.4, fill:true, pointRadius:4, pointBackgroundColor:'#FF8C00', pointBorderColor:'#0A0A0A', pointBorderWidth:2 },
          { label:'G마켓', data:[0,3822800,2310200,...Array(9).fill(0)], borderColor:'#4C9AFF', backgroundColor:'rgba(76,154,255,0.07)', borderWidth:2.5, tension:0.4, fill:true, pointRadius:4, pointBackgroundColor:'#4C9AFF', pointBorderColor:'#0A0A0A', pointBorderWidth:2 },
          { label:'플레이오토', data:[0,0,0,...Array(9).fill(0)], borderColor:'#51CF66', backgroundColor:'rgba(81,207,102,0.05)', borderWidth:2, tension:0.4, fill:true, pointRadius:3, pointBackgroundColor:'#51CF66', pointBorderColor:'#0A0A0A', pointBorderWidth:2 }
        ]
      },
      options: {
        responsive:true, maintainAspectRatio:true,
        interaction:{mode:'index',intersect:false},
        plugins:{ legend:{display:false}, tooltip:{...tooltip, callbacks:{label:(c)=>` ${c.dataset.label}: ₩${c.raw.toLocaleString()}`}} },
        scales:{
          x:{grid:dkGrid, ticks:{color:'#444', font:{size:11}}},
          y:{grid:dkGrid, ticks:{color:'#444', font:{size:11}, callback:(v)=>v>=1000000?`₩${(v/1000000).toFixed(0)}M`:`₩${(v/1000).toFixed(0)}K`}}
        }
      }
    })
  }

  // 마켓별 도넛
  const donutEl = document.getElementById('ac-donut-mkt')
  if (donutEl) {
    if (acCharts.donut) acCharts.donut.destroy()
    acCharts.donut = new Chart(donutEl.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: ['신세계몰','G마켓','플레이오토(EMP)'],
        datasets: [{ data:[93445300,6133000,0], backgroundColor:['#FF8C00','#4C9AFF','#51CF66'], borderColor:'#0E0E0E', borderWidth:3, hoverOffset:10 }]
      },
      options: {
        responsive:true, maintainAspectRatio:true, cutout:'70%',
        plugins:{
          legend:{position:'bottom', labels:{color:'#777', padding:16, font:{size:12}, boxWidth:10, borderRadius:4}},
          tooltip:{...tooltip, callbacks:{label:(c)=>` ${c.label}: ₩${c.raw.toLocaleString()} (${c.raw>0?(c.raw/99578300*100).toFixed(1)+'%':'0%'})`}}
        }
      }
    })
  }

  // 사이트별 가로 바
  const barSiteEl = document.getElementById('ac-bar-site')
  if (barSiteEl) {
    if (acCharts.barSite) acCharts.barSite.destroy()
    const siteLabels = ['MUSINSA','GSShop','LOTTEON','ABCmart','GrandStage','Nike','FOLDERStyle','SSG']
    const siteVals   = [50636200,18172600,11091500,6941900,4918500,3090000,2056400,1944000]
    acCharts.barSite = new Chart(barSiteEl.getContext('2d'), {
      type: 'bar',
      data: {
        labels: siteLabels,
        datasets: [{ label:'매출', data:siteVals,
          backgroundColor: siteVals.map((_,i)=>`rgba(255,140,0,${0.85 - i*0.08})`),
          borderRadius:5, borderSkipped:false }]
      },
      options: {
        indexAxis:'y', responsive:true, maintainAspectRatio:true,
        plugins:{legend:{display:false}, tooltip:{...tooltip, callbacks:{label:(c)=>` ₩${c.raw.toLocaleString()}`}}},
        scales:{
          x:{grid:dkGrid, ticks:{color:'#444', font:{size:10}, callback:(v)=>`₩${(v/1000000).toFixed(0)}M`}},
          y:{grid:{display:false}, ticks:{color:'#999', font:{size:11}}}
        }
      }
    })
  }

  // 주문상태 도넛
  const statusEl = document.getElementById('ac-donut-status')
  if (statusEl) {
    if (acCharts.status) acCharts.status.destroy()
    acCharts.status = new Chart(statusEl.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: ['결제완료','배송대기','배송완료','반품/취소'],
        datasets: [{ data:[344,1488,1917,391], backgroundColor:['#FFD93D','#4C9AFF','#51CF66','#FF6B6B'], borderColor:'#0E0E0E', borderWidth:3, hoverOffset:8 }]
      },
      options: {
        responsive:true, maintainAspectRatio:true, cutout:'65%',
        plugins:{
          legend:{position:'bottom', labels:{color:'#777', padding:12, font:{size:11}, boxWidth:8, borderRadius:3}},
          tooltip:{...tooltip, callbacks:{label:(c)=>` ${c.label}: ${c.raw.toLocaleString()}건`}}
        }
      }
    })
  }

  // 월별 주문건수 바
  const ordersEl = document.getElementById('ac-bar-orders')
  if (ordersEl) {
    if (acCharts.orders) acCharts.orders.destroy()
    acCharts.orders = new Chart(ordersEl.getContext('2d'), {
      type: 'bar',
      data: {
        labels: ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'],
        datasets: [{ label:'주문건수', data:[2232,994,391,...Array(9).fill(0)],
          backgroundColor:'rgba(255,140,0,0.72)', borderRadius:6, borderSkipped:false }]
      },
      options: {
        responsive:true, maintainAspectRatio:true,
        plugins:{legend:{display:false}, tooltip:{...tooltip, callbacks:{label:(c)=>` ${c.raw.toLocaleString()}건`}}},
        scales:{
          x:{grid:{display:false}, ticks:{color:'#444', font:{size:11}}},
          y:{grid:dkGrid, ticks:{color:'#444', font:{size:11}}}
        }
      }
    })
  }
}

/* ──────────────────────────────────────────
   대시보드 페이지
────────────────────────────────────────── */
const dbCharts = {}

// 상품관리 KPI 카드 업데이트
async function updateDashboardCards() {
  try {
    const products = await storage.getAll('products')
    const orders   = await storage.getAll('orders')

    const totalSales = orders.reduce((sum, o) => sum + (o.salePrice || 0), 0)
    const orderCount = orders.length
    // 마켓에 등록되어 판매중인 상품만 카운트
    const selling = products.filter(p => (p.registeredAccounts || []).length > 0).length

    const elSales = document.getElementById('dash-total-sales')
    const elCount = document.getElementById('dash-order-count')
    const elCollected = document.getElementById('dash-collected')
    const elSelling = document.getElementById('dash-selling')

    if (elSales) elSales.textContent = '₩' + totalSales.toLocaleString()
    if (elCount) elCount.textContent = orderCount.toLocaleString() + '건 누적'
    if (elCollected) elCollected.innerHTML = products.length + '<span style="font-size:1rem; color:#888; font-weight:500;">개</span>'
    if (elSelling) elSelling.innerHTML = selling + '<span style="font-size:1rem; color:#888; font-weight:500;">개</span>'
  } catch(e) {
    console.warn('대시보드 카드 업데이트 실패:', e)
  }
}

// 대시보드 차트 초기화
async function initDashboardCharts() {
  const now = new Date()
  const dbDate = document.getElementById('db-date')
  if (dbDate) dbDate.textContent = now.toLocaleDateString('ko-KR', { year:'numeric', month:'long', day:'numeric' })

  try {
    const products = await storage.getAll('products')
    const el = document.getElementById('db-collected')
    if (el) el.textContent = products.length + '개'
  } catch(e) {}

  // 최근 일주일 테이블
  const weekTbody = document.getElementById('db-week-tbody')
  if (weekTbody) {
    const weekData = [
      { date:'03/11(화)', total:3820000, fulfill:3620000, rate:94.8 },
      { date:'03/10(월)', total:4150000, fulfill:4010000, rate:96.6 },
      { date:'03/09(일)', total:1980000, fulfill:1820000, rate:91.9 },
      { date:'03/08(토)', total:2340000, fulfill:2100000, rate:89.7 },
      { date:'03/07(금)', total:5210000, fulfill:5050000, rate:96.9 },
      { date:'03/06(목)', total:4780000, fulfill:4560000, rate:95.4 },
      { date:'03/05(수)', total:3690000, fulfill:3500000, rate:94.8 },
    ]
    weekTbody.innerHTML = weekData.map(r => `
      <tr>
        <td>${r.date}</td>
        <td class="num-orange">₩${r.total.toLocaleString()}</td>
        <td class="num-blue">₩${r.fulfill.toLocaleString()}</td>
        <td class="num-green">${r.rate.toFixed(1)}%</td>
      </tr>`).join('')
  }

  // 금월/전월 비교 테이블
  const monthTbody = document.getElementById('db-month-tbody')
  if (monthTbody) {
    const rows = [
      { label:'3월 (금월)', total:25970000, fulfill:24660000, rate:94.9 },
      { label:'2월 (전월)', total:31480000, fulfill:29820000, rate:94.7 },
      { label:'전월 대비', total:'+▲5,510,000', fulfill:'+▲1,160,000', rate:'+0.2%', diff:true },
    ]
    monthTbody.innerHTML = rows.map(r => {
      if (r.diff) {
        return `<tr style="background:rgba(255,140,0,0.04);">
          <td style="font-weight:600; color:#FFB84D;">${r.label}</td>
          <td style="text-align:right; color:#4C9AFF; font-weight:600;">${r.total}</td>
          <td style="text-align:right; color:#4C9AFF; font-weight:600;">${r.fulfill}</td>
          <td style="text-align:right; color:#51CF66; font-weight:600;">${r.rate}</td>
        </tr>`
      }
      return `<tr>
        <td>${r.label}</td>
        <td class="num-orange">₩${r.total.toLocaleString()}</td>
        <td class="num-blue">₩${r.fulfill.toLocaleString()}</td>
        <td class="num-green">${r.rate.toFixed(1)}%</td>
      </tr>`
    }).join('')
  }

  const months = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
  const scaleOpts = {
    x:{ ticks:{ color:'#555', font:{ size:11 } }, grid:{ color:'rgba(255,255,255,0.03)' } },
    y:{ ticks:{ color:'#555', font:{ size:11 }, callback: v => '₩'+(v/1000000).toFixed(1)+'M' }, grid:{ color:'rgba(255,255,255,0.06)' } }
  }

  // 월별 매출 추이 (line)
  const lineEl = document.getElementById('db-line')
  if (lineEl) {
    if (dbCharts.line) dbCharts.line.destroy()
    const ssgData  = [0,3822800,2310200,8541000,12330000,9820000,7450000,0,0,0,0,0]
    const gmktData = [52296000,29988400,11260900,21430000,18970000,24560000,19340000,0,0,0,0,0]
    dbCharts.line = new Chart(lineEl.getContext('2d'), {
      type: 'line',
      data: { labels: months,
        datasets: [
          { label:'신세계몰', data:ssgData,  borderColor:'#FF8C00', backgroundColor:'rgba(255,140,0,0.08)',  tension:0.4, pointRadius:3, pointBackgroundColor:'#FF8C00', fill:true },
          { label:'G마켓',   data:gmktData, borderColor:'#4C9AFF', backgroundColor:'rgba(76,154,255,0.08)', tension:0.4, pointRadius:3, pointBackgroundColor:'#4C9AFF', fill:true }
        ]
      },
      options: { responsive:true, maintainAspectRatio:false, plugins:{ legend:{ display:false } }, scales: scaleOpts }
    })
  }

  // 마켓별 도넛
  const donutEl = document.getElementById('db-donut')
  if (donutEl) {
    if (dbCharts.donut) dbCharts.donut.destroy()
    dbCharts.donut = new Chart(donutEl.getContext('2d'), {
      type: 'doughnut',
      data: { labels:['G마켓','신세계몰'], datasets:[{ data:[6133000,93445300], backgroundColor:['#4C9AFF','#FF8C00'], borderWidth:0, hoverOffset:6 }] },
      options: { responsive:true, maintainAspectRatio:false, cutout:'65%', plugins:{ legend:{ position:'bottom', labels:{ color:'#888', font:{ size:11 }, padding:12 } } } }
    })
  }

  // 수입사이트별 가로바
  const barSiteEl = document.getElementById('db-bar-site')
  if (barSiteEl) {
    if (dbCharts.barSite) dbCharts.barSite.destroy()
    const sLabels = ['MUSINSA','GSShop','LOTTEON','ABCmart','GrandStage','Nike','FOLDERStyle','SSG']
    const sVals   = [50636200,18172600,11091500,6941900,4918500,3090000,2056400,1944000]
    dbCharts.barSite = new Chart(barSiteEl.getContext('2d'), {
      type:'bar',
      data:{ labels:sLabels, datasets:[{ data:sVals, backgroundColor:['#FF8C00','#FFB84D','#4C9AFF','#51CF66','#FF6B6B','#CC5DE8','#74C0FC','#A9E34B'], borderRadius:4 }] },
      options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{ legend:{ display:false } }, scales:{ x:{ ticks:{ color:'#555', font:{ size:10 }, callback:v=>'₩'+(v/1000000).toFixed(1)+'M' }, grid:{ color:'rgba(255,255,255,0.04)' } }, y:{ ticks:{ color:'#888', font:{ size:10 } }, grid:{ display:false } } } }
    })
  }

  // 마켓 사업자별 상품등록현황 테이블
  const mktTbody = document.getElementById('db-mkt-reg-tbody')
  if (mktTbody) {
    const mktNames  = ['G마켓 - A사업자','G마켓 - B사업자','옥션 - A사업자','옥션 - B사업자','스마트스토어','쿠팡','롯데ON','11번가','신세계몰']
    const mktReg    = [1842,934,1755,812,1230,980,640,520,320]
    const mktColors = ['#4C9AFF','#74C0FC','#4C9AFF','#74C0FC','#51CF66','#FF6B6B','#FFB84D','#FF8C00','#A9E34B']
    const total     = mktReg.reduce((a,b)=>a+b,0)
    mktTbody.innerHTML = mktNames.map((n,i) => {
      const pct = ((mktReg[i]/total)*100).toFixed(1)
      return `<tr>
        <td>${n}</td>
        <td class="num-orange">${mktReg[i].toLocaleString()}</td>
        <td>${pct}%</td>
        <td style="min-width:120px;">
          <div style="height:6px; background:#1A1A1A; border-radius:3px;">
            <div style="height:6px; width:${pct}%; background:${mktColors[i]}; border-radius:3px;"></div>
          </div>
        </td>
      </tr>`
    }).join('')
  }
}

/* ──────────────────────────────────────────
   설정 페이지
────────────────────────────────────────── */

// 설정 탭 전환
function switchSettingsTab(market, clickedBtn) {
  document.querySelectorAll('.stg-panel').forEach(p => p.style.display = 'none')
  document.querySelectorAll('.stg-tab').forEach(t => t.classList.remove('stg-tab-on'))
  const panel = document.getElementById('stg-' + market)
  if (panel) panel.style.display = ''
  if (clickedBtn) clickedBtn.classList.add('stg-tab-on')
}
