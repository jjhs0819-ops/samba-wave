/**
 * AI 상품 가공 모듈
 * 이미지, 상품명 등을 AI로 자동 가공
 */

class AIProcessor {
    constructor() {
        this.apiKey = null;
        this.useLocalAI = true; // 로컬 AI로 시작, 나중에 Claude API로 변경 가능
    }

    /**
     * API 키 설정
     */
    setAPIKey(key) {
        this.apiKey = key;
        this.useLocalAI = false;
    }

    /**
     * 상품명 AI 개선
     */
    async improveProductName(productName, category = '') {
        if (!productName) return productName;

        if (this.useLocalAI) {
            return this.localImproveProductName(productName, category);
        } else {
            return await this.claudeImproveProductName(productName, category);
        }
    }

    /**
     * 로컬 상품명 개선
     */
    localImproveProductName(productName, category) {
        // 정규화
        let improved = productName.trim();

        // 여러 공백을 하나로
        improved = improved.replace(/\s+/g, ' ');

        // 특수문자 정리
        improved = improved.replace(/[|\/\\]/g, ' ');

        // 앞뒤 공백 제거
        improved = improved.trim();

        // 첫 글자 대문자 (영문인 경우)
        if (/^[a-z]/.test(improved)) {
            improved = improved.charAt(0).toUpperCase() + improved.slice(1);
        }

        // 카테고리 추가 (있는 경우)
        if (category && !improved.toLowerCase().includes(category.toLowerCase())) {
            improved = `${category} ${improved}`;
        }

        // 브랜드/모델 정보 강조
        const brandPatterns = [
            { regex: /^(apple|samsung|lg|sony|canon|nikon)/i, brand: '$1' },
            { regex: /(\d+\D{0,2})mm/i, keep: true }
        ];

        // 너무 긴 경우 축약
        if (improved.length > 100) {
            improved = improved.substring(0, 97) + '...';
        }

        return improved;
    }

    /**
     * Claude API로 상품명 개선
     */
    async claudeImproveProductName(productName, category) {
        try {
            const response = await fetch('/api/ai/improve-product-name', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ productName, category })
            });

            const data = await response.json();
            return data.improvedName || productName;
        } catch (error) {
            console.error('Claude API 호출 실패:', error);
            return this.localImproveProductName(productName, category);
        }
    }

    /**
     * 이미지 분석 및 배경 제거 제안
     */
    async analyzeImage(imageFile) {
        if (!imageFile || !imageFile.type.startsWith('image/')) {
            return { error: '이미지 파일만 업로드 가능합니다' };
        }

        if (this.useLocalAI) {
            return await this.localAnalyzeImage(imageFile);
        } else {
            return await this.claudeAnalyzeImage(imageFile);
        }
    }

    /**
     * 로컬 이미지 분석
     */
    async localAnalyzeImage(imageFile) {
        return new Promise((resolve) => {
            const reader = new FileReader();

            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    const analysis = {
                        width: img.width,
                        height: img.height,
                        size: (imageFile.size / 1024).toFixed(2) + ' KB',
                        recommendations: this.getImageRecommendations(img.width, img.height, imageFile.size)
                    };

                    resolve(analysis);
                };
                img.src = e.target.result;
            };

            reader.readAsDataURL(imageFile);
        });
    }

    /**
     * 이미지 최적화 제안
     */
    getImageRecommendations(width, height, fileSize) {
        const recommendations = [];

        // 크기 제안
        if (width < 300 || height < 300) {
            recommendations.push('⚠️ 이미지 크기가 너무 작습니다 (최소 300x300px 권장)');
        }
        if (width > 2000 || height > 2000) {
            recommendations.push('📦 이미지를 리사이징해서 파일 크기를 줄리세요');
        }

        // 비율 제안
        const ratio = width / height;
        if (ratio < 0.7 || ratio > 1.4) {
            recommendations.push('📐 세로 또는 가로 비율이 비정상적입니다');
        } else {
            recommendations.push('✅ 이미지 비율이 좋습니다');
        }

        // 파일 크기 제안
        if (fileSize > 2000000) {
            recommendations.push('💾 파일 크기를 2MB 이하로 압축해주세요');
        }

        recommendations.push('💡 배경 제거: 흰색/단색 배경으로 변경하면 더 전문적으로 보입니다');
        recommendations.push('🎨 추천 처리: 명도 조정, 콘트라스트 향상');

        return recommendations;
    }

    /**
     * Claude API로 이미지 분석
     */
    async claudeAnalyzeImage(imageFile) {
        try {
            const reader = new FileReader();

            return new Promise((resolve) => {
                reader.onload = async (e) => {
                    const base64 = e.target.result.split(',')[1];

                    const response = await fetch('/api/ai/analyze-image', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ imageData: base64, fileName: imageFile.name })
                    });

                    const data = await response.json();
                    resolve(data);
                };

                reader.readAsDataURL(imageFile);
            });
        } catch (error) {
            console.error('이미지 분석 실패:', error);
            return { error: '이미지 분석에 실패했습니다' };
        }
    }

    /**
     * 이미지 리사이징 (클라이언트 사이드)
     */
    async resizeImage(imageFile, maxWidth = 1200, maxHeight = 1200) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();

            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    let { width, height } = img;

                    // 비율 유지하며 리사이징
                    if (width > height) {
                        if (width > maxWidth) {
                            height *= maxWidth / width;
                            width = maxWidth;
                        }
                    } else {
                        if (height > maxHeight) {
                            width *= maxHeight / height;
                            height = maxHeight;
                        }
                    }

                    canvas.width = width;
                    canvas.height = height;

                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob((blob) => {
                        resolve({
                            blob,
                            width: Math.round(width),
                            height: Math.round(height),
                            originalSize: (imageFile.size / 1024).toFixed(2) + ' KB',
                            newSize: (blob.size / 1024).toFixed(2) + ' KB'
                        });
                    }, 'image/jpeg', 0.85);
                };

                img.src = e.target.result;
            };

            reader.readAsDataURL(imageFile);
        });
    }

    /**
     * 이미지 미리보기 생성
     */
    generatePreview(imageFile) {
        return new Promise((resolve) => {
            const reader = new FileReader();

            reader.onload = (e) => {
                resolve(e.target.result);
            };

            reader.readAsDataURL(imageFile);
        });
    }

    /**
     * 카테고리별 상품명 템플릿
     */
    getProductNameTemplate(category) {
        const templates = {
            '의류': '[브랜드] [스타일] [색상] [사이즈]',
            '신발': '[브랜드] [유형] [색상] 사이즈 [사이즈]',
            '가방': '[브랜드] [유형] [색상/패턴]',
            '액세서리': '[브랜드] [제품명] [색상]',
            '전자제품': '[브랜드] [모델명] [스펙]',
            '가구': '[유형] [색상] [사이즈]',
            '화장품': '[브랜드] [제품명] [용량]'
        };

        return templates[category] || '[브랜드] [제품명] [색상/사이즈]';
    }

    /**
     * 마진율 AI 제안
     */
    calculateRecommendedMargin(cost, category = '일반') {
        // 카테고리별 평균 마진율
        const margins = {
            '의류': 40,
            '신발': 35,
            '가방': 40,
            '액세서리': 50,
            '전자제품': 25,
            '가구': 30,
            '화장품': 45,
            '일반': 35
        };

        return margins[category] || 35;
    }
}

// 글로벌 인스턴스
const aiProcessor = new AIProcessor();
