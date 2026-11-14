// Inicializa el replica set de un solo nodo para MongoDB

const host = "mongo:27017";
const replicaSet = "rs0";
const maxAttempts = 10;
const retryDelayMs = 2000;

function replicaSetReady() {
  try {
    const status = rs.status();
    print(`El replica set ${status.set} ya estaba inicializado.`);
    return true;
  } catch (error) {
    if (error.codeName !== "NotYetInitialized") {
      throw error;
    }
    return false;
  }
}

function initiateWithRetries() {
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      rs.initiate({
        _id: replicaSet,
        members: [{ _id: 0, host: host }],
      });
      print(
        `Replica set ${replicaSet} iniciado con el miembro ${host} ` +
          `(intento ${attempt}).`
      );
      return;
    } catch (error) {
      if (replicaSetReady()) {
        return;
      }
      lastError = error;
      print(`Intento ${attempt}/${maxAttempts} falló: ${error.message}`);
      sleep(retryDelayMs);
    }
  }

  throw new Error(
    `No se pudo iniciar el replica set ${replicaSet}: ${lastError.message}`
  );
}

if (!replicaSetReady()) {
  initiateWithRetries();
}
