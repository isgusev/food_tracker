<script setup lang="ts">
// Сканер: BarcodeDetector (Chrome на Android/Mac), иначе ZXing из public/vendor (Safari и все браузеры на iPhone).
// Камера — только на https или localhost; цифры всегда можно ввести руками.
// marks — «Честный знак»: DataMatrix + EAN, сканирование подряд (каждый новый код — событие, повтор — нет),
// «Готово» закрывает. qr — QR-код чека.
import { onBeforeUnmount, onMounted, ref } from "vue";
import ModalSheet from "../ModalSheet.vue";

const props = defineProps<{ title?: string; count?: number; marks?: boolean; qr?: boolean }>();
const emit = defineEmits<{ code: [code: string]; close: [] }>();

type ZXingLib = {
  BarcodeFormat: Record<string, unknown>;
  DecodeHintType: Record<string, unknown>;
  BrowserMultiFormatReader: new (hints: Map<unknown, unknown>, delay: number) => {
    reset(): void;
    decodeFromConstraints(c: MediaStreamConstraints, v: HTMLVideoElement, cb: (r: { getText(): string } | null) => void): Promise<void>;
  };
};
type Detector = { detect(v: HTMLVideoElement): Promise<{ rawValue: string }[]> };
type DetectorCtor = { new (o: { formats: string[] }): Detector; getSupportedFormats?: () => Promise<string[]> };
const w = window as unknown as { ZXing?: ZXingLib; BarcodeDetector?: DetectorCtor };

let zxingLoading: Promise<ZXingLib> | null = null;
function loadZxing(): Promise<ZXingLib> {
  if (w.ZXing) return Promise.resolve(w.ZXing);
  zxingLoading ||= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = `${import.meta.env.BASE_URL}vendor/zxing.min.js`;
    s.onload = () => (w.ZXing ? resolve(w.ZXing) : reject(new Error("нет ZXing")));
    s.onerror = () => reject(new Error("не удалось загрузить распознавание"));
    document.head.appendChild(s);
  });
  return zxingLoading;
}

const EAN_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
const video = ref<HTMLVideoElement | null>(null);
const manual = ref("");
const status = ref("");
const supported = !!navigator.mediaDevices?.getUserMedia && window.isSecureContext;
let stop: () => void = () => {};
let done = false;
const seen = new Set<string>();

function found(raw: string) {
  const code = String(raw);
  if (props.marks) {
    if (seen.has(code)) return;            // та же пачка ещё в кадре
    seen.add(code);
    navigator.vibrate?.(60);
    emit("code", code);
    return;
  }
  if (done) return;
  done = true;
  stop();
  emit("code", code);
}

async function withDetector() {
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
  const v = video.value!;
  v.srcObject = stream;
  await v.play();
  const Ctor = w.BarcodeDetector!;
  const supportedFormats = (await Ctor.getSupportedFormats?.()) || EAN_FORMATS;
  const wanted = props.qr ? ["qr_code"] : props.marks ? ["data_matrix", ...EAN_FORMATS] : EAN_FORMATS;
  const formats = wanted.filter((f) => supportedFormats.includes(f));
  if ((props.marks && !formats.includes("data_matrix")) || (props.qr && !formats.length)) {
    stream.getTracks().forEach((t) => t.stop());
    throw new Error("no-datamatrix");
  }
  const detector = new Ctor({ formats });
  const timer = setInterval(async () => {
    try { for (const x of await detector.detect(v)) found(x.rawValue); } catch { /* кадр не готов */ }
  }, 300);
  stop = () => { clearInterval(timer); stream.getTracks().forEach((t) => t.stop()); };
}

async function withZxing() {
  const Z = await loadZxing();
  const F = Z.BarcodeFormat;
  let formats: unknown[] = [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E];
  if (props.marks) formats.unshift(F.DATA_MATRIX);
  if (props.qr) formats = [F.QR_CODE];
  const reader = new Z.BrowserMultiFormatReader(new Map([[Z.DecodeHintType.POSSIBLE_FORMATS, formats]]), 300);
  stop = () => { try { reader.reset(); } catch { /* уже остановлен */ } };
  await reader.decodeFromConstraints({ video: { facingMode: "environment" } }, video.value!, (r) => { if (r) found(r.getText()); });
}

async function start() {
  if (!supported) { status.value = "Камера доступна только по https — введите цифры под штрихкодом."; return; }
  try {
    status.value = props.qr ? "Наведите камеру на QR-код внизу чека"
      : props.marks ? "Наведите камеру на квадратный код «Честного знака» — пачки можно сканировать подряд"
        : "Наведите камеру на штрихкод";
    if (w.BarcodeDetector) {
      try { await withDetector(); } catch (e) {
        if ((e as Error)?.message === "no-datamatrix") await withZxing(); else throw e;
      }
    } else await withZxing();
  } catch (e) {
    status.value = (e as { name?: string })?.name === "NotAllowedError"
      ? "Нет разрешения на камеру — разрешите доступ в настройках браузера или введите цифры."
      : "Камера недоступна — введите цифры под штрихкодом.";
  }
}
onMounted(start);
onBeforeUnmount(() => stop());

function submit() {
  if (props.marks || props.qr) {
    const c = manual.value.trim();
    if (c.length >= 10) { found(c); manual.value = ""; }
    return;
  }
  const c = manual.value.replace(/\D/g, "");
  if (c.length >= 8) found(c);
}
const heading = () => props.title || (props.qr ? "QR-код чека" : props.marks ? "Код «Честного знака»" : "Штрихкод");
</script>

<template>
  <ModalSheet :title="heading()" @close="stop(); emit('close')">
    <video v-if="supported" ref="video" class="cam" playsinline muted autoplay></video>
    <p class="small muted">{{ status }}</p>
    <p v-if="marks && count != null" class="small"><b>Отсканировано пачек: {{ count }}</b></p>
    <div class="manual">
      <input v-model="manual" :inputmode="marks || qr ? 'text' : 'numeric'"
             :placeholder="qr ? 't=…&s=…&fn=…&i=…&fp=…&n=1' : marks ? 'код с упаковки, если камера не читает' : '4600000000000'"
             :aria-label="qr ? 'Строка QR-кода' : marks ? 'Код маркировки' : 'Цифры штрихкода'" @keydown.enter="submit">
      <button :class="marks ? '' : 'fill'" @click="submit">{{ marks ? "Добавить" : qr ? "Загрузить" : "Найти" }}</button>
    </div>
    <template v-if="marks" #foot><button class="fill" @click="stop(); emit('close')">Готово</button></template>
  </ModalSheet>
</template>

<style scoped>
.cam { width: 100%; max-height: 50vh; border-radius: var(--r-in); background: var(--ink); }
p { margin: 0; }
.manual { display: flex; gap: 8px; }
.manual input { flex: 1; min-width: 0; }
</style>
