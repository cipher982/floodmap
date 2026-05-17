/*
 * WebGPU shallow-water solver scaffold for the Flood Sandbox lab.
 *
 * The engine runs the two core virtual-pipes passes on the GPU:
 * 1. compute per-cell outflow to four neighbors
 * 2. gather neighbor outflows and update water depth
 *
 * The lab reads the water buffer back for diagnostics and canvas rendering.
 */

class FloodSimWebGpu {
  constructor({ width, height, bed, water, cellSize = 10 }) {
    this.width = width;
    this.height = height;
    this.bedInput = bed;
    this.waterInput = water;
    this.cellSize = cellSize;
    this.device = null;
    this.adapter = null;
    this.buffers = {};
    this.bindGroups = {};
    this.pipelines = {};
    this.stepCount = 0;
    this.readWater = new Float32Array(width * height);
  }

  static async isSupported() {
    return !!globalThis.navigator?.gpu;
  }

  async init() {
    if (!globalThis.navigator?.gpu) {
      throw new Error("WebGPU is not available in this browser");
    }
    this.adapter = await navigator.gpu.requestAdapter({
      powerPreference: "high-performance"
    });
    if (!this.adapter) throw new Error("No WebGPU adapter available");
    this.device = await this.adapter.requestDevice();
    this.createBuffers();
    this.createPipelines();
    return this;
  }

  createBuffers() {
    const usage = GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST | GPUBufferUsage.COPY_SRC;
    const waterBytes = this.width * this.height * 4;
    this.buffers.bed = this.createBuffer(this.bedInput, usage);
    this.buffers.waterA = this.createBuffer(this.waterInput, usage);
    this.buffers.waterB = this.device.createBuffer({ size: waterBytes, usage });
    this.buffers.outflow = this.device.createBuffer({
      size: this.width * this.height * 16,
      usage
    });
    this.buffers.params = this.device.createBuffer({
      size: 64,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST
    });
    this.buffers.readback = this.device.createBuffer({
      size: waterBytes,
      usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST
    });
  }

  createBuffer(values, usage) {
    const source = values instanceof Float32Array ? values : new Float32Array(values);
    const buffer = this.device.createBuffer({
      size: source.byteLength,
      usage,
      mappedAtCreation: true
    });
    new Float32Array(buffer.getMappedRange()).set(source);
    buffer.unmap();
    return buffer;
  }

  createPipelines() {
    const module = this.device.createShaderModule({ code: FLOOD_SIM_WGSL });
    const layout = this.device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: "read-only-storage" } },
        { binding: 1, visibility: GPUShaderStage.COMPUTE, buffer: { type: "read-only-storage" } },
        { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: "storage" } },
        { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: "storage" } },
        { binding: 4, visibility: GPUShaderStage.COMPUTE, buffer: { type: "uniform" } }
      ]
    });

    this.pipelines.outflow = this.device.createComputePipeline({
      layout: this.device.createPipelineLayout({ bindGroupLayouts: [layout] }),
      compute: { module, entryPoint: "compute_outflow" }
    });
    this.pipelines.update = this.device.createComputePipeline({
      layout: this.device.createPipelineLayout({ bindGroupLayouts: [layout] }),
      compute: { module, entryPoint: "update_water" }
    });
    this.bindGroups.aToB = this.createBindGroup(layout, this.buffers.waterA, this.buffers.waterB);
    this.bindGroups.bToA = this.createBindGroup(layout, this.buffers.waterB, this.buffers.waterA);
  }

  createBindGroup(layout, sourceWater, targetWater) {
    return this.device.createBindGroup({
      layout,
      entries: [
        { binding: 0, resource: { buffer: this.buffers.bed } },
        { binding: 1, resource: { buffer: sourceWater } },
        { binding: 2, resource: { buffer: this.buffers.outflow } },
        { binding: 3, resource: { buffer: targetWater } },
        { binding: 4, resource: { buffer: this.buffers.params } }
      ]
    });
  }

  writeParams(options = {}) {
    const values = new Float32Array(16);
    values[0] = this.width;
    values[1] = this.height;
    values[2] = options.dt ?? 0.18;
    values[3] = options.conductance ?? 0.19;
    values[4] = options.rainRate ?? 0;
    values[5] = options.source?.x ?? -9999;
    values[6] = options.source?.y ?? -9999;
    values[7] = options.source?.radius ?? 0;
    values[8] = options.source?.amount ?? 0;
    this.device.queue.writeBuffer(this.buffers.params, 0, values);
  }

  step(options = {}) {
    this.writeParams(options);
    const even = this.stepCount % 2 === 0;
    const encoder = this.device.createCommandEncoder();
    const workgroupsX = Math.ceil(this.width / 8);
    const workgroupsY = Math.ceil(this.height / 8);

    const pass = encoder.beginComputePass();
    const bindGroup = even ? this.bindGroups.aToB : this.bindGroups.bToA;
    pass.setPipeline(this.pipelines.outflow);
    pass.setBindGroup(0, bindGroup);
    pass.dispatchWorkgroups(workgroupsX, workgroupsY);
    pass.setPipeline(this.pipelines.update);
    pass.setBindGroup(0, bindGroup);
    pass.dispatchWorkgroups(workgroupsX, workgroupsY);
    pass.end();

    this.device.queue.submit([encoder.finish()]);
    this.stepCount += 1;
  }

  async readWaterBuffer() {
    const source = this.stepCount % 2 === 0 ? this.buffers.waterA : this.buffers.waterB;
    const encoder = this.device.createCommandEncoder();
    encoder.copyBufferToBuffer(source, 0, this.buffers.readback, 0, this.readWater.byteLength);
    this.device.queue.submit([encoder.finish()]);
    await this.buffers.readback.mapAsync(GPUMapMode.READ);
    this.readWater.set(new Float32Array(this.buffers.readback.getMappedRange()));
    this.buffers.readback.unmap();
    return this.readWater;
  }

  async adapterInfo() {
    if (typeof this.adapter?.requestAdapterInfo === "function") {
      return await this.adapter.requestAdapterInfo();
    }
    return { description: "WebGPU adapter info unavailable" };
  }
}

const FLOOD_SIM_WGSL = `
struct Params {
  width: f32,
  height: f32,
  dt: f32,
  conductance: f32,
  rainRate: f32,
  sourceX: f32,
  sourceY: f32,
  sourceRadius: f32,
  sourceAmount: f32,
  pad0: f32,
  pad1: f32,
  pad2: f32,
  pad3: f32,
  pad4: f32,
  pad5: f32,
  pad6: f32,
}

@group(0) @binding(0) var<storage, read> bed: array<f32>;
@group(0) @binding(1) var<storage, read> water: array<f32>;
@group(0) @binding(2) var<storage, read_write> outflow: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> water_out: array<f32>;
@group(0) @binding(4) var<uniform> params: Params;

fn idx(x: u32, y: u32) -> u32 {
  return y * u32(params.width) + x;
}

fn surface(x: u32, y: u32) -> f32 {
  let i = idx(x, y);
  return bed[i] + water[i];
}

@compute @workgroup_size(8, 8)
fn compute_outflow(@builtin(global_invocation_id) id: vec3<u32>) {
  let width = u32(params.width);
  let height = u32(params.height);
  if (id.x >= width || id.y >= height) {
    return;
  }
  let i = idx(id.x, id.y);
  let available = max(0.0, water[i]);
  if (available <= 0.0) {
    outflow[i] = vec4<f32>(0.0);
    return;
  }

  let here = bed[i] + water[i];
  var f = vec4<f32>(0.0); // left, right, up, down
  if (id.x > 0u) {
    f.x = max(0.0, here - surface(id.x - 1u, id.y)) * params.conductance * params.dt;
  }
  if (id.x + 1u < width) {
    f.y = max(0.0, here - surface(id.x + 1u, id.y)) * params.conductance * params.dt;
  }
  if (id.y > 0u) {
    f.z = max(0.0, here - surface(id.x, id.y - 1u)) * params.conductance * params.dt;
  }
  if (id.y + 1u < height) {
    f.w = max(0.0, here - surface(id.x, id.y + 1u)) * params.conductance * params.dt;
  }

  let total = f.x + f.y + f.z + f.w;
  if (total > available && total > 0.0) {
    f = f * (available / total);
  }
  outflow[i] = f;
}

@compute @workgroup_size(8, 8)
fn update_water(@builtin(global_invocation_id) id: vec3<u32>) {
  let width = u32(params.width);
  let height = u32(params.height);
  if (id.x >= width || id.y >= height) {
    return;
  }
  let i = idx(id.x, id.y);
  let outgoing = outflow[i].x + outflow[i].y + outflow[i].z + outflow[i].w;
  var incoming = 0.0;
  if (id.x > 0u) {
    incoming += outflow[idx(id.x - 1u, id.y)].y;
  }
  if (id.x + 1u < width) {
    incoming += outflow[idx(id.x + 1u, id.y)].x;
  }
  if (id.y > 0u) {
    incoming += outflow[idx(id.x, id.y - 1u)].w;
  }
  if (id.y + 1u < height) {
    incoming += outflow[idx(id.x, id.y + 1u)].z;
  }

  var next = max(0.0, water[i] + incoming - outgoing + params.rainRate * params.dt);
  let dx = f32(id.x) - params.sourceX;
  let dy = f32(id.y) - params.sourceY;
  if (params.sourceAmount > 0.0 && params.sourceRadius > 0.0) {
    let dist = sqrt(dx * dx + dy * dy);
    if (dist <= params.sourceRadius) {
      let falloff = 0.35 + 0.65 * (1.0 - dist / max(1.0, params.sourceRadius));
      next += params.sourceAmount * params.dt * falloff;
    }
  }
  water_out[i] = next;
}
`;

if (typeof window !== "undefined") {
  window.FloodSimWebGpu = FloodSimWebGpu;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FloodSimWebGpu };
}
