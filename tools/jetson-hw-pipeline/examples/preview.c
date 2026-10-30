/* YUYV camera preview through NVMM/VIC, using the GStreamer C API. */
#include <gst/gst.h>
#include <signal.h>
#include <stdio.h>

static volatile sig_atomic_t interrupted;
static void stop_signal(int number) { (void)number; interrupted = 1; }
static GstPadProbeReturn count_buffer(GstPad *pad, GstPadProbeInfo *info, gpointer data)
{
    (void)pad; (void)info;
    ++*(guint64 *)data; /* Metadata only; no mapping or copy of image pixels. */
    return GST_PAD_PROBE_OK;
}

int main(int argc, char **argv)
{
    gchar *device = NULL;
    g_autofree gchar *pixel_format = NULL;
    gint width = 640, height = 480, fps = 60, frames = 180;
    gboolean headless = FALSE;
    GOptionEntry options[] = {
        {"device", 0, 0, G_OPTION_ARG_STRING, &device, "V4L2 device", "PATH"},
        {"width", 0, 0, G_OPTION_ARG_INT, &width, "Width", "N"},
        {"height", 0, 0, G_OPTION_ARG_INT, &height, "Height", "N"},
        {"fps", 0, 0, G_OPTION_ARG_INT, &fps, "Frame rate", "N"},
        {"frames", 0, 0, G_OPTION_ARG_INT, &frames, "Frames; 0 until Ctrl+C", "N"},
        {"format", 0, 0, G_OPTION_ARG_STRING, &pixel_format, "YUYV, AB24, AR24, Y16, Y14 or Y16_BE", "FORMAT"},
        {"headless", 0, 0, G_OPTION_ARG_NONE, &headless, "Disable rendering", NULL},
        {NULL, 0, 0, G_OPTION_ARG_NONE, NULL, NULL, NULL}
    };
    GError *error = NULL;
    GOptionContext *options_context = g_option_context_new("- NVMM camera preview");
    g_option_context_add_main_entries(options_context, options, NULL);
    g_option_context_add_group(options_context, gst_init_get_option_group());
    if (!g_option_context_parse(options_context, &argc, &argv, &error)) {
        fprintf(stderr, "%s\n", error->message);
        g_error_free(error); g_option_context_free(options_context); g_free(device); return 2;
    }
    g_option_context_free(options_context);
    if (width <= 0 || height <= 0 || fps <= 0 || frames < 0) {
        fprintf(stderr, "Width, height and fps must be positive; frames must be non-negative\n");
        g_free(device); return 2;
    }
    const gchar *fmt = pixel_format ? pixel_format : "YUYV";
    gboolean gray = g_str_equal(fmt, "Y16") || g_str_equal(fmt, "Y14") || g_str_equal(fmt, "Y16_BE");
    const gchar *gst_fmt = gray || g_str_equal(fmt, "AB24") ? "RGBA" :
                           g_str_equal(fmt, "AR24") ? "BGRx" :
                           g_str_equal(fmt, "YUYV") ? "YUY2" : NULL;
    if (!gst_fmt) { fprintf(stderr, "Unsupported format\n"); g_free(device); return 2; }
    if (headless) g_unsetenv("DISPLAY");
    const gchar *display = g_getenv("DISPLAY");
    if (!headless && (!display || !g_regex_match_simple("^(unix/?)?:[0-9]+(\\.[0-9]+)?$", display, 0, 0))) {
        fprintf(stderr, "NVMM display requires local X11; use --headless over SSH\n");
        g_free(device); return 2;
    }
    if (!headless) g_setenv("__GL_YIELD", "USLEEP", FALSE);
    const gchar *conversion = g_str_equal(fmt, "YUYV") || g_str_equal(fmt, "AR24") ?
        " ! nvvidconv compute-hw=2 ! video/x-raw(memory:NVMM),format=NV12" : "";
    gchar *description = g_strdup_printf(
        "egv4l2camerasrc name=camera ! "
        "video/x-raw(memory:NVMM),format=%s,width=%d,height=%d,framerate=%d/1%s ! %s",
        gst_fmt, width, height, fps, conversion, headless ? "fakesink sync=false" :
        "nv3dsink sync=false processing-deadline=0");
    GstElement *pipeline = gst_parse_launch(description, &error);
    g_free(description);
    if (!pipeline || error) {
        fprintf(stderr, "Pipeline creation: %s\n", error ? error->message : "failed");
        if (error) g_error_free(error);
        if (pipeline) gst_object_unref(pipeline);
        g_free(device); return 1;
    }
    GstElement *camera = gst_bin_get_by_name(GST_BIN(pipeline), "camera");
    if (gray) g_object_set(camera, "capture-format", fmt, "preview", TRUE, NULL);
    g_object_set(camera, "device", device ? device : "/dev/video0",
                 "num-buffers", frames ? frames : -1, NULL);
    g_free(device);
    guint64 captured = 0;
    GstPad *pad = gst_element_get_static_pad(camera, "src");
    gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, count_buffer, &captured, NULL);
    gst_object_unref(pad); gst_object_unref(camera);
    GstBus *bus = gst_element_get_bus(pipeline);
    signal(SIGINT, stop_signal); signal(SIGTERM, stop_signal);
    int result = 0;
    if (gst_element_set_state(pipeline, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        fprintf(stderr, "Cannot start pipeline\n"); result = 1;
    } else while (!interrupted) {
        GstMessage *message = gst_bus_timed_pop_filtered(bus, 100 * GST_MSECOND,
                                      GST_MESSAGE_ERROR | GST_MESSAGE_EOS);
        if (!message) continue;
        if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
            gchar *details = NULL;
            gst_message_parse_error(message, &error, &details);
            fprintf(stderr, "%s\n%s\n", error->message, details ? details : "");
            g_error_free(error); g_free(details); result = 1;
        }
        gst_message_unref(message); break;
    }
    gst_element_set_state(pipeline, GST_STATE_NULL);
    printf("Captured %" G_GUINT64_FORMAT " buffers; no CPU pixel mapping.\n", captured);
    gst_object_unref(bus); gst_object_unref(pipeline);
    return result;
}
