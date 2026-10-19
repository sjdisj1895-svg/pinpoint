// 카카오맵 JavaScript SDK 로더. 공식 타입 패키지가 없어 kakao 객체는 any로 다룬다.
/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    kakao?: any;
  }
}

let loading: Promise<any> | null = null;

/** SDK를 한 번만 불러오고 kakao 객체를 돌려준다. 실패하거나 시간이 지나면 reject (호출한 쪽이 다른 지도로 대체한다). */
export function loadKakaoSdk(appKey: string, timeoutMs = 10000): Promise<any> {
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    if (window.kakao?.maps?.load) {
      window.kakao.maps.load(() => resolve(window.kakao));
      return;
    }
    const timer = setTimeout(() => reject(new Error("카카오맵 SDK를 불러오는 시간이 초과됐어요")), timeoutMs);
    const script = document.createElement("script");
    script.async = true;
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(appKey)}&autoload=false`;
    script.onload = () => {
      try {
        window.kakao.maps.load(() => {
          clearTimeout(timer);
          resolve(window.kakao);
        });
      } catch (e) {
        clearTimeout(timer);
        reject(e);
      }
    };
    script.onerror = () => {
      clearTimeout(timer);
      reject(new Error("카카오맵 SDK를 불러오지 못했어요 (광고 차단·네트워크 확인)"));
    };
    document.head.appendChild(script);
  });
  loading.catch(() => {
    loading = null; // 다음에 다시 시도할 수 있게
  });
  return loading;
}
