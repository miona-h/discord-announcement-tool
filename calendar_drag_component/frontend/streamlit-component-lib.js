function sendMessageToStreamlitClient(type, data) {
  window.parent.postMessage(Object.assign({isStreamlitMessage: true, type: type}, data), "*");
}
const Streamlit = {
  setComponentReady: () => sendMessageToStreamlitClient("streamlit:componentReady", {apiVersion: 1}),
  setFrameHeight: height => sendMessageToStreamlitClient("streamlit:setFrameHeight", {height: height}),
  setComponentValue: value => sendMessageToStreamlitClient("streamlit:setComponentValue", {value: value}),
  RENDER_EVENT: "streamlit:render",
  events: {
    addEventListener: (type, callback) => window.addEventListener("message", event => {
      if (event.data.type === type) {
        event.detail = event.data;
        callback(event);
      }
    })
  }
};
