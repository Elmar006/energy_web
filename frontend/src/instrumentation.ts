export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { validateRuntime } = await import("../runtime/policy.mjs");
    validateRuntime(process.env);
  }
}
