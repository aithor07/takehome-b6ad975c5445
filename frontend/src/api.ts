const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function checkBackendHealth(): Promise<{status: string}>{
    const response = await fetch(`${API_BASE_URL}/health`);
    if (!response.ok){
        throw new Error('No se puedo conectar con el backend');
    }
    return response.json();
}